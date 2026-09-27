"""Corpus-wide invariant validation test suite inspecting actual generated artifacts."""

import json
from pathlib import Path
import pytest
from ragtune.models import BenchmarkQuery, PassageChunk


@pytest.fixture(scope="module")
def corpus_chunks():
    chunks_path = Path("data/processed/corpus_chunks.jsonl")
    assert chunks_path.exists(), "corpus_chunks.jsonl does not exist"
    chunks = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(PassageChunk.model_validate_json(line))
    return chunks


@pytest.fixture(scope="module")
def partitioned_chunks():
    part_path = Path("data/processed/partitioned_chunks.jsonl")
    assert part_path.exists(), "partitioned_chunks.jsonl does not exist"
    chunks = []
    with open(part_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(PassageChunk.model_validate_json(line))
    return chunks


@pytest.fixture(scope="module")
def manifest():
    manifest_path = Path("benchmarks/manifest.json")
    assert manifest_path.exists(), "manifest.json does not exist"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def partition_manifest():
    p_path = Path("benchmarks/partition_manifest.json")
    assert p_path.exists(), "partition_manifest.json does not exist"
    with open(p_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def pilot_queries():
    pilot_path = Path("benchmarks/pilot_benchmark.jsonl")
    assert pilot_path.exists(), "pilot_benchmark.jsonl does not exist"
    queries = []
    with open(pilot_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                queries.append(BenchmarkQuery.model_validate_json(line))
    return queries


def test_maximum_token_limit(corpus_chunks):
    """Corpus-wide invariant: no emitted chunk exceeds configured max_tokens (512)."""
    assert len(corpus_chunks) > 0
    max_tok = max(c.token_count for c in corpus_chunks)
    assert max_tok <= 512, f"Corpus max token length {max_tok} exceeds hard limit 512"
    for c in corpus_chunks:
        assert c.token_count <= 512, f"Chunk {c.chunk_id} in {c.relative_file_path} has {c.token_count} tokens > 512"


def test_no_empty_chunks(corpus_chunks):
    """Corpus-wide invariant: no empty chunks or chunks consisting solely of headers/breadcrumbs."""
    for c in corpus_chunks:
        cleaned = c.content.strip()
        assert len(cleaned) > 0, f"Empty chunk detected: {c.chunk_id}"
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
        assert not all(l.startswith("#") for l in lines), f"Chunk {c.chunk_id} consists solely of headers"


def test_no_duplicate_chunk_ids(corpus_chunks):
    """Corpus-wide invariant: every chunk ID is strictly unique."""
    ids = [c.chunk_id for c in corpus_chunks]
    assert len(ids) == len(set(ids)), f"Duplicate chunk IDs found in corpus! Total={len(ids)}, Unique={len(set(ids))}"


def test_chunk_id_determinism(corpus_chunks):
    """Corpus-wide invariant: computing chunk ID twice yields identical identifiers."""
    from ragtune.models import compute_chunk_id
    for c in corpus_chunks[:100]:
        recomputed = compute_chunk_id(
            ecosystem=c.ecosystem,
            source_ref=c.source_ref,
            relative_file_path=c.relative_file_path,
            header_path=c.header_path,
            chunk_index=c.chunk_index,
        )
        assert c.chunk_id == recomputed


def test_every_chunk_references_existing_manifest_source(corpus_chunks, manifest):
    """Corpus-wide invariant: every chunk references an authentic manifest source."""
    valid_ecos = {s["ecosystem"]: s["actual_resolved_tag"] for s in manifest["sources"]}
    for c in corpus_chunks:
        assert c.ecosystem in valid_ecos, f"Unknown ecosystem {c.ecosystem}"
        assert c.source_ref == valid_ecos[c.ecosystem], f"Source ref mismatch for {c.chunk_id}"


def test_every_chunk_belongs_to_exactly_one_partition(partitioned_chunks):
    """Corpus-wide invariant: every partitioned chunk belongs to exactly one partition."""
    valid_partitions = {"train", "validation", "frozen_test"}
    for c in partitioned_chunks:
        assert c.partition in valid_partitions, f"Invalid partition {c.partition} for chunk {c.chunk_id}"


def test_zero_source_file_overlap_between_partitions(partition_manifest):
    """Corpus-wide invariant: absolute zero source-file overlap between partitions."""
    train_files = {f"{x['ecosystem']}::{x['file_path']}" for x in partition_manifest["files"]["train"]}
    val_files = {f"{x['ecosystem']}::{x['file_path']}" for x in partition_manifest["files"]["validation"]}
    test_files = {f"{x['ecosystem']}::{x['file_path']}" for x in partition_manifest["files"]["frozen_test"]}

    assert len(train_files & val_files) == 0, f"Overlap between train and validation: {train_files & val_files}"
    assert len(train_files & test_files) == 0, f"Overlap between train and test: {train_files & test_files}"
    assert len(val_files & test_files) == 0, f"Overlap between validation and test: {val_files & test_files}"


def test_frozen_test_chunks_never_occur_in_training_inputs(partitioned_chunks):
    """Corpus-wide invariant: frozen_test chunk IDs never appear in train or validation sets."""
    test_ids = {c.chunk_id for c in partitioned_chunks if c.partition == "frozen_test"}
    train_val_ids = {c.chunk_id for c in partitioned_chunks if c.partition in ("train", "validation")}

    overlap = test_ids & train_val_ids
    assert len(overlap) == 0, f"Contamination: frozen_test chunks appear in train/val: {overlap}"


def test_pilot_positives_all_belong_to_frozen_test_sources(pilot_queries, partitioned_chunks):
    """Benchmark invariant: all pilot queries have grade >= 2 judgments from frozen_test partition."""
    chunk_map = {c.chunk_id: c for c in partitioned_chunks}

    assert len(pilot_queries) == 16, f"Expected 16 pilot queries, got {len(pilot_queries)}"

    for q in pilot_queries:
        assert len(q.relevant_chunks) > 0, f"Query {q.query_id} has no relevant chunks"
        high_grade = [j for j in q.relevant_chunks if j.grade >= 2]
        assert len(high_grade) > 0, f"Query {q.query_id} has no grade >= 2 positives"

        for j in high_grade:
            assert j.chunk_id in chunk_map, f"Judgment {j.chunk_id} not found in partitioned chunks"
            c = chunk_map[j.chunk_id]
            assert c.partition == "frozen_test", (
                f"Query {q.query_id} positive {j.chunk_id} is in partition {c.partition}, MUST be frozen_test"
            )


def test_every_grade_judgment_points_to_existing_chunk(pilot_queries, partitioned_chunks):
    """Benchmark invariant: every relevance judgment references an authentic passage chunk."""
    chunk_ids = {c.chunk_id for c in partitioned_chunks}
    for q in pilot_queries:
        for j in q.relevant_chunks:
            assert j.chunk_id in chunk_ids, f"Orphaned judgment chunk_id {j.chunk_id} in {q.query_id}"
