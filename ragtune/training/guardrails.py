"""Training and partition discipline guardrails for RAGTune.

Strictly prevents test data leakage into training pipelines, hard-negative mining,
and hyperparameter selection.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from ragtune.models import BenchmarkQuery


class FrozenTestLeakageError(ValueError):
    """Raised when frozen_test data or queries attempt to enter training or validation workflows."""
    pass


class PartitionDisciplineError(ValueError):
    """Raised when data from an incorrect partition is used in a partitioned workflow."""
    pass


class TrainingTriple(BaseModel):
    """Contrastive training triple (Query, Positive, Hard Negative) with partition provenance."""
    
    query_id: str
    query_text: str
    query_source_partition: str
    positive_chunk_id: str
    positive_source_partition: str
    negative_chunk_id: str
    negative_source_partition: str
    teacher_margin: Optional[float] = Field(default=None, description="Score margin under teacher cross-encoder")

    model_config = {"frozen": True}


def validate_training_query(query: BenchmarkQuery | Dict[str, Any]) -> None:
    """Assert query is strictly from the train partition and not frozen_test."""
    if isinstance(query, BenchmarkQuery):
        partition = query.source_partition
        qid = query.query_id
    else:
        partition = query.get("source_partition")
        qid = query.get("query_id", "unknown")

    if partition == "frozen_test":
        raise FrozenTestLeakageError(
            f"PROHIBITED: Query '{qid}' originates from the 'frozen_test' partition. "
            "Frozen-test queries MUST NOT generate training data, hard negatives, "
            "or guide model tuning."
        )

    if partition != "train":
        raise PartitionDisciplineError(
            f"Training query '{qid}' must have source_partition='train', but found '{partition}'."
        )


def validate_validation_query(query: BenchmarkQuery | Dict[str, Any]) -> None:
    """Assert query is strictly from the validation partition and not frozen_test."""
    if isinstance(query, BenchmarkQuery):
        partition = query.source_partition
        qid = query.query_id
    else:
        partition = query.get("source_partition")
        qid = query.get("query_id", "unknown")

    if partition == "frozen_test":
        raise FrozenTestLeakageError(
            f"PROHIBITED: Query '{qid}' originates from 'frozen_test' but was passed as a validation query."
        )

    if partition != "validation":
        raise PartitionDisciplineError(
            f"Validation query '{qid}' must have source_partition='validation', but found '{partition}'."
        )


def validate_final_test_query(query: BenchmarkQuery | Dict[str, Any]) -> None:
    """Assert final evaluation query is strictly from the frozen_test partition."""
    if isinstance(query, BenchmarkQuery):
        partition = query.source_partition
        qid = query.query_id
    else:
        partition = query.get("source_partition")
        qid = query.get("query_id", "unknown")

    if partition != "frozen_test":
        raise PartitionDisciplineError(
            f"Final test query '{qid}' must have source_partition='frozen_test', but found '{partition}'."
        )


def validate_training_triple(
    triple: TrainingTriple | Dict[str, Any],
    chunk_partition_lookup: Optional[Dict[str, str]] = None,
) -> None:
    """Assert that neither query, positive chunk, nor negative chunk originates from frozen_test.
    
    Args:
        triple: TrainingTriple instance or dictionary containing triple fields.
        chunk_partition_lookup: Optional mapping from chunk_id to partition name
            for authoritative verification against the corpus.
    """
    if isinstance(triple, TrainingTriple):
        q_part = triple.query_source_partition
        pos_part = triple.positive_source_partition
        neg_part = triple.negative_source_partition
        qid = triple.query_id
        pos_id = triple.positive_chunk_id
        neg_id = triple.negative_chunk_id
    else:
        q_part = triple.get("query_source_partition", "")
        pos_part = triple.get("positive_source_partition", "")
        neg_part = triple.get("negative_source_partition", "")
        qid = triple.get("query_id", "unknown")
        pos_id = triple.get("positive_chunk_id", "unknown")
        neg_id = triple.get("negative_chunk_id", "unknown")

    # If authoritative lookup is provided, override and verify
    if chunk_partition_lookup is not None:
        if pos_id in chunk_partition_lookup:
            pos_part = chunk_partition_lookup[pos_id]
        if neg_id in chunk_partition_lookup:
            neg_part = chunk_partition_lookup[neg_id]

    # Check for frozen_test leakage
    if q_part == "frozen_test":
        raise FrozenTestLeakageError(
            f"PROHIBITED: Training triple query '{qid}' belongs to 'frozen_test'."
        )
    if pos_part == "frozen_test":
        raise FrozenTestLeakageError(
            f"PROHIBITED: Training triple positive chunk '{pos_id}' belongs to 'frozen_test'."
        )
    if neg_part == "frozen_test":
        raise FrozenTestLeakageError(
            f"PROHIBITED: Training triple negative chunk '{neg_id}' belongs to 'frozen_test'."
        )

    # Assert training data discipline (positives and queries should strictly be 'train')
    if q_part != "train":
        raise PartitionDisciplineError(
            f"Training triple query '{qid}' has partition '{q_part}', expected 'train'."
        )
    if pos_part != "train":
        raise PartitionDisciplineError(
            f"Training triple positive '{pos_id}' has partition '{pos_part}', expected 'train'."
        )
