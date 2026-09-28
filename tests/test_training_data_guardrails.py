"""Unit and guardrail integrity tests for RAGTune training data foundation."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from ragtune.training.guardrails import (
    FrozenTestLeakageError,
    PartitionDisciplineError,
    validate_training_triple,
)


@pytest.fixture(scope="module")
def partition_lookup() -> dict[str, str]:
    path = Path("data/processed/partitioned_chunks.jsonl")
    assert path.exists(), f"Partitioned chunks file not found: {path}"
    lookup = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                lookup[d["chunk_id"]] = d["partition"]
    return lookup


def test_retriever_train_v0_zero_leakage(partition_lookup: dict[str, str]):
    """Assert all triples in retriever_train_v0.jsonl strictly belong to train partition."""
    train_path = Path("data/training/retriever_train_v0.jsonl")
    assert train_path.exists(), f"Training triples file not found: {train_path}"

    with open(train_path, "r", encoding="utf-8") as f:
        triples = [json.loads(line) for line in f if line.strip()]

    assert len(triples) > 0, "Training set should not be empty."

    for t in triples:
        # 1. Direct guardrail assertion
        validate_training_triple(t, chunk_partition_lookup=partition_lookup)

        # 2. Strict partition check
        assert t["query_source_partition"] == "train"
        assert t["positive_source_partition"] == "train"
        assert t["negative_source_partition"] == "train"

        pos_id = t["positive_chunk_id"]
        neg_id = t["negative_chunk_id"]

        assert partition_lookup[pos_id] == "train", f"Positive chunk {pos_id} not in train partition!"
        assert partition_lookup[neg_id] == "train", f"Negative chunk {neg_id} not in train partition!"
        assert pos_id != neg_id, f"Positive and negative chunk are identical: {pos_id}"

        # 3. Teacher margin check
        assert t.get("teacher_margin") is not None
        assert t["teacher_margin"] >= 0.15, f"Teacher margin below threshold: {t['teacher_margin']}"


def test_guardrail_catches_frozen_test_leakage(partition_lookup: dict[str, str]):
    """Assert validate_training_triple raises FrozenTestLeakageError on frozen_test chunk."""
    # Find a frozen_test chunk
    frozen_id = next(cid for cid, p in partition_lookup.items() if p == "frozen_test")

    bad_triple = {
        "query_id": "test_leak",
        "query_text": "sample query",
        "query_source_partition": "train",
        "positive_chunk_id": frozen_id,
        "positive_source_partition": "train",  # lied about partition, lookup should catch
        "negative_chunk_id": "some_other_id",
        "negative_source_partition": "train",
    }

    with pytest.raises(FrozenTestLeakageError):
        validate_training_triple(bad_triple, chunk_partition_lookup=partition_lookup)


def test_guardrail_catches_validation_leakage(partition_lookup: dict[str, str]):
    """Assert validate_training_triple raises PartitionDisciplineError on validation chunk."""
    val_id = next(cid for cid, p in partition_lookup.items() if p == "validation")

    bad_triple = {
        "query_id": "test_val_leak",
        "query_text": "sample query",
        "query_source_partition": "train",
        "positive_chunk_id": val_id,
        "positive_source_partition": "train",
        "negative_chunk_id": "some_other_id",
        "negative_source_partition": "train",
    }

    with pytest.raises(PartitionDisciplineError):
        validate_training_triple(bad_triple, chunk_partition_lookup=partition_lookup)


def test_hard_negatives_v1_zero_leakage(partition_lookup: dict[str, str]):
    """Assert all triples in hard_negatives_v1.jsonl strictly belong to train partition."""
    hn_path = Path("data/training/hard_negatives_v1.jsonl")
    assert hn_path.exists(), f"Hard negatives file not found: {hn_path}"

    with open(hn_path, "r", encoding="utf-8") as f:
        triples = [json.loads(line) for line in f if line.strip()]

    assert len(triples) > 0, "Hard negatives set should not be empty."

    for t in triples:
        validate_training_triple(t, chunk_partition_lookup=partition_lookup)
        assert t["query_source_partition"] == "train"
        assert t["positive_source_partition"] == "train"
        assert t["negative_source_partition"] == "train"
        assert partition_lookup[t["positive_chunk_id"]] == "train"
        assert partition_lookup[t["negative_chunk_id"]] == "train"
        assert t["positive_chunk_id"] != t["negative_chunk_id"]
        assert t["teacher_margin"] >= 0.25
        assert t["verification_status"] == "ACCEPTED_VERIFIED_HARD_NEGATIVE"


def test_matched_easy_control_v1_zero_leakage(partition_lookup: dict[str, str]):
    """Assert all triples in e4_matched_easy_control_v1.jsonl strictly belong to train partition."""
    ctrl_path = Path("data/training/e4_matched_easy_control_v1.jsonl")
    assert ctrl_path.exists(), f"Matched control file not found: {ctrl_path}"

    with open(ctrl_path, "r", encoding="utf-8") as f:
        triples = [json.loads(line) for line in f if line.strip()]

    assert len(triples) == 739, f"Matched control must contain exactly 739 rows, got {len(triples)}"

    for t in triples:
        validate_training_triple(t, chunk_partition_lookup=partition_lookup)
        assert t["query_source_partition"] == "train"
        assert t["positive_source_partition"] == "train"
        assert t["negative_source_partition"] == "train"
        assert partition_lookup[t["positive_chunk_id"]] == "train"
        assert partition_lookup[t["negative_chunk_id"]] == "train"
        assert t["positive_chunk_id"] != t["negative_chunk_id"]
        assert t["source_path"] != t["positive_source_path"]
        assert t["verification_status"] == "MATCHED_EASY_CONTROL_NEGATIVE"


