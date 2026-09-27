"""Automated tests for training and partition leakage guardrails."""

import pytest
from ragtune.models import BenchmarkQuery, RelevanceJudgment
from ragtune.training.guardrails import (
    FrozenTestLeakageError,
    PartitionDisciplineError,
    TrainingTriple,
    validate_final_test_query,
    validate_training_query,
    validate_training_triple,
    validate_validation_query,
)


def _make_sample_query(qid: str, source_partition: str, role: str) -> BenchmarkQuery:
    return BenchmarkQuery(
        query_id=qid,
        domain="postgresql",
        query_text="Sample query text for testing guardrails",
        typology="direct_lookup",
        provenance_type="human_authored",
        source_partition=source_partition,  # type: ignore
        role=role,  # type: ignore
        relevant_chunks=[
            RelevanceJudgment(chunk_id="test_chunk_001", grade=3, notes="Canonical evidence")
        ],
    )


def test_validate_training_query_rejects_frozen_test():
    q_frozen = _make_sample_query("q_frozen", "frozen_test", "final_test")
    with pytest.raises(FrozenTestLeakageError, match="PROHIBITED"):
        validate_training_query(q_frozen)


def test_validate_training_query_rejects_validation():
    q_val = _make_sample_query("q_val", "validation", "development")
    with pytest.raises(PartitionDisciplineError, match="must have source_partition='train'"):
        validate_training_query(q_val)


def test_validate_training_query_accepts_train():
    q_train = _make_sample_query("q_train", "train", "training")
    # Should not raise
    validate_training_query(q_train)


def test_validate_validation_query_rejects_frozen_test():
    q_frozen = _make_sample_query("q_frozen", "frozen_test", "final_test")
    with pytest.raises(FrozenTestLeakageError, match="PROHIBITED"):
        validate_validation_query(q_frozen)


def test_validate_validation_query_rejects_train():
    q_train = _make_sample_query("q_train", "train", "training")
    with pytest.raises(PartitionDisciplineError, match="must have source_partition='validation'"):
        validate_validation_query(q_train)


def test_validate_validation_query_accepts_validation():
    q_val = _make_sample_query("q_val", "validation", "development")
    # Should not raise
    validate_validation_query(q_val)


def test_validate_final_test_query_rejects_non_frozen():
    q_train = _make_sample_query("q_train", "train", "training")
    with pytest.raises(PartitionDisciplineError, match="source_partition='frozen_test'"):
        validate_final_test_query(q_train)


def test_training_triple_rejects_frozen_test_query():
    triple = TrainingTriple(
        query_id="q_leak",
        query_text="Leak query",
        query_source_partition="frozen_test",
        positive_chunk_id="c_pos",
        positive_source_partition="train",
        negative_chunk_id="c_neg",
        negative_source_partition="train",
    )
    with pytest.raises(FrozenTestLeakageError, match="query.*belongs to 'frozen_test'"):
        validate_training_triple(triple)


def test_training_triple_rejects_frozen_test_positive():
    triple = TrainingTriple(
        query_id="q_ok",
        query_text="Valid query",
        query_source_partition="train",
        positive_chunk_id="c_frozen_pos",
        positive_source_partition="frozen_test",
        negative_chunk_id="c_neg",
        negative_source_partition="train",
    )
    with pytest.raises(FrozenTestLeakageError, match="positive chunk.*belongs to 'frozen_test'"):
        validate_training_triple(triple)


def test_training_triple_rejects_frozen_test_negative():
    triple = TrainingTriple(
        query_id="q_ok",
        query_text="Valid query",
        query_source_partition="train",
        positive_chunk_id="c_pos",
        positive_source_partition="train",
        negative_chunk_id="c_frozen_neg",
        negative_source_partition="frozen_test",
    )
    with pytest.raises(FrozenTestLeakageError, match="negative chunk.*belongs to 'frozen_test'"):
        validate_training_triple(triple)


def test_training_triple_rejects_authoritative_lookup_frozen_negative():
    triple = TrainingTriple(
        query_id="q_ok",
        query_text="Valid query",
        query_source_partition="train",
        positive_chunk_id="c_pos",
        positive_source_partition="train",
        negative_chunk_id="c_suspicious_neg",
        negative_source_partition="train",  # Claimed to be train
    )
    # But authoritative lookup reveals it is from frozen_test!
    lookup = {"c_pos": "train", "c_suspicious_neg": "frozen_test"}
    with pytest.raises(FrozenTestLeakageError, match="negative chunk.*belongs to 'frozen_test'"):
        validate_training_triple(triple, chunk_partition_lookup=lookup)


def test_training_triple_accepts_valid_train_data():
    triple = TrainingTriple(
        query_id="q_train_001",
        query_text="Valid train query",
        query_source_partition="train",
        positive_chunk_id="c_train_pos",
        positive_source_partition="train",
        negative_chunk_id="c_train_neg",
        negative_source_partition="train",
        teacher_margin=1.85,
    )
    lookup = {"c_train_pos": "train", "c_train_neg": "train"}
    # Should not raise
    validate_training_triple(triple, chunk_partition_lookup=lookup)
