"""Unit and integration tests for SQLiteLexicalRetriever."""

import json
from pathlib import Path
import pytest
from ragtune.retrieval.lexical_retriever import SQLiteLexicalRetriever, sanitize_query_to_fts5


def test_sanitize_query_to_fts5():
    # Regular query
    q = "How to configure a projected volume in Kubernetes?"
    fts_q = sanitize_query_to_fts5(q)
    assert '"projected"' in fts_q
    assert '"volume"' in fts_q
    assert '"kubernetes"' in fts_q
    assert " OR " in fts_q

    # Dotted identifiers
    q_dotted = "torch.utils.checkpoint backward pass"
    fts_dotted = sanitize_query_to_fts5(q_dotted)
    assert '"torch.utils.checkpoint"' in fts_dotted
    assert '"torch"' in fts_dotted

    # Empty string
    assert sanitize_query_to_fts5("") == ""
    assert sanitize_query_to_fts5("??? !!!") == ""


def test_retriever_in_memory():
    # In-memory test db
    db_path = "data/indices/test_in_memory.db"
    retriever = SQLiteLexicalRetriever(db_path=db_path)
    
    # Check index building on actual corpus
    corpus_path = "data/processed/corpus_chunks.jsonl"
    if Path(corpus_path).exists():
        count = retriever.build_index(corpus_path, overwrite=True)
        assert count == 11645

        # Query known document
        results = retriever.search("advisory lock transaction end", top_k=5)
        assert len(results) == 5
        assert all(isinstance(score, float) for _, score in results)
        
        # Test search with domain filter
        pg_results = retriever.search("advisory lock", top_k=5, ecosystem="postgresql")
        assert len(pg_results) > 0
    
    retriever.close()
    if Path(db_path).exists():
        Path(db_path).unlink()


def test_e0_pilot_metrics_artifacts():
    metrics_path = Path("benchmarks/e0_pilot_metrics.json")
    assert metrics_path.exists(), "benchmarks/e0_pilot_metrics.json must exist"

    with open(metrics_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["total_queries"] == 16
    assert data["corpus_chunks_indexed"] == 11645
    assert "overall_metrics" in data
    assert "recall_at_10" in data["overall_metrics"]
    assert "mrr_at_10" in data["overall_metrics"]
    assert "ndcg_at_10" in data["overall_metrics"]
    assert data["overall_metrics"]["recall_at_10"] >= 0.70
