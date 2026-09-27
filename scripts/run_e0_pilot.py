"""Run E0 Lexical Baseline on Pilot Benchmark.

Executes SQLite FTS5 BM25 retrieval over the complete frozen corpus (11,645 chunks)
for the 16 pilot queries. Computes IR metrics (Recall@K, MRR@10, NDCG@10), captures
retrieval latency, and exports predictions and failure triage artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Dict, List

from ragtune.evaluation.metrics import mrr_at_k, ndcg_at_k, recall_at_k
from ragtune.retrieval.lexical_retriever import SQLiteLexicalRetriever


def run_e0_pilot(
    corpus_chunks_path: str = "data/processed/corpus_chunks.jsonl",
    benchmark_path: str = "benchmarks/pilot_benchmark.jsonl",
    db_path: str = "data/indices/sqlite_fts.db",
    predictions_output_path: str = "benchmarks/e0_pilot_predictions.jsonl",
    failures_output_path: str = "benchmarks/e0_pilot_failures.jsonl",
    metrics_output_path: str = "benchmarks/e0_pilot_metrics.json",
    top_k: int = 50,
) -> Dict[str, Any]:
    """Execute E0 pilot evaluation."""
    print("=" * 70)
    print("RAGTUNE EXPERIMENT E0-PILOT: LEXICAL BASELINE (SQLite FTS5 BM25)")
    print("=" * 70)

    # 1. Initialize retriever and index
    retriever = SQLiteLexicalRetriever(db_path=db_path)
    print(f"Building / verifying index from: {corpus_chunks_path}...")
    chunk_count = retriever.build_index(corpus_chunks_path, overwrite=False)
    print(f"Index verified with {chunk_count} chunks.")

    # 2. Load pilot benchmark
    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    print(f"Loaded {len(queries)} pilot benchmark queries from {benchmark_path}.")

    # 3. Execute retrieval
    print(f"Executing retrieval for {len(queries)} queries (top_k={top_k})...")
    predictions, telemetry = retriever.search_batch(queries, top_k=top_k)
    print(f"Retrieval complete in {telemetry['total_elapsed_sec']:.4f}s ({telemetry['queries_per_sec']:.1f} QPS).")
    print(f"Latency: mean={telemetry['mean_latency_ms']:.2f}ms, p50={telemetry['p50_latency_ms']:.2f}ms, p95={telemetry['p95_latency_ms']:.2f}ms")

    # 4. Evaluate metrics
    recalls_1: List[float] = []
    recalls_5: List[float] = []
    recalls_10: List[float] = []
    recalls_20: List[float] = []
    mrrs_10: List[float] = []
    ndcgs_10: List[float] = []

    per_query_results = []
    failures = []

    domain_stats: Dict[str, Dict[str, List[float]]] = {}

    for q, p in zip(queries, predictions):
        domain = q["domain"]
        if domain not in domain_stats:
            domain_stats[domain] = {
                "r1": [], "r5": [], "r10": [], "r20": [], "mrr10": [], "ndcg10": []
            }

        retrieved = p["retrieved_chunk_ids"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        canonical_id = next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None)
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}

        r1 = recall_at_k(retrieved, positives, k=1)
        r5 = recall_at_k(retrieved, positives, k=5)
        r10 = recall_at_k(retrieved, positives, k=10)
        r20 = recall_at_k(retrieved, positives, k=20)
        mrr = mrr_at_k(retrieved, positives, k=10)
        ndcg = ndcg_at_k(retrieved, graded_rel, k=10)

        recalls_1.append(r1)
        recalls_5.append(r5)
        recalls_10.append(r10)
        recalls_20.append(r20)
        mrrs_10.append(mrr)
        ndcgs_10.append(ndcg)

        domain_stats[domain]["r1"].append(r1)
        domain_stats[domain]["r5"].append(r5)
        domain_stats[domain]["r10"].append(r10)
        domain_stats[domain]["r20"].append(r20)
        domain_stats[domain]["mrr10"].append(mrr)
        domain_stats[domain]["ndcg10"].append(ndcg)

        hits_50 = [cid for cid in retrieved[:50] if cid in positives]
        hits_10 = [cid for cid in retrieved[:10] if cid in positives]
        hits_1 = [cid for cid in retrieved[:1] if cid in positives]

        status = "SUCCESS"
        if len(hits_50) == 0:
            status = "RETRIEVAL_FAILURE_TOP50"
        elif len(hits_10) == 0:
            status = "RETRIEVAL_FAILURE_TOP10"

        canonical_rank = None
        if canonical_id and canonical_id in retrieved:
            canonical_rank = retrieved.index(canonical_id) + 1

        query_eval = {
            "query_id": q["query_id"],
            "domain": domain,
            "query_text": q["query_text"],
            "typology": q["typology"],
            "status": status,
            "canonical_chunk_id": canonical_id,
            "canonical_rank": canonical_rank,
            "recall_at_1": r1,
            "recall_at_5": r5,
            "recall_at_10": r10,
            "recall_at_20": r20,
            "mrr_at_10": mrr,
            "ndcg_at_10": ndcg,
            "hits_at_10": len(hits_10),
            "total_positives": len(positives),
            "top_1_score": p["scores"][0] if p["scores"] else None,
            "latency_ms": p["latency_ms"],
        }
        per_query_results.append(query_eval)

        if status != "SUCCESS":
            failures.append({
                "query_id": q["query_id"],
                "domain": domain,
                "typology": q["typology"],
                "query_text": q["query_text"],
                "failure_type": status,
                "diagnostic_status": "DIAGNOSTIC_ONLY",
                "eligible_for_training": False,
                "source_partition": "frozen_test",
                "purpose": "engineering_smoke_test_only",
                "canonical_chunk_id": canonical_id,
                "canonical_rank": canonical_rank,
                "positive_chunk_ids": list(positives),
                "top_5_retrieved": [
                    {"chunk_id": cid, "score": score}
                    for cid, score in zip(retrieved[:5], p["scores"][:5])
                ],
            })

    # 5. Domain aggregates
    domain_summary = {}
    for d, s in domain_stats.items():
        n = len(s["r1"])
        domain_summary[d] = {
            "query_count": n,
            "recall_at_1": float(sum(s["r1"]) / n),
            "recall_at_5": float(sum(s["r5"]) / n),
            "recall_at_10": float(sum(s["r10"]) / n),
            "recall_at_20": float(sum(s["r20"]) / n),
            "mrr_at_10": float(sum(s["mrr10"]) / n),
            "ndcg_at_10": float(sum(s["ndcg10"]) / n),
        }

    n_total = len(queries)
    aggregate_summary = {
        "experiment_id": "E0-pilot",
        "description": "Lexical Baseline (SQLite FTS5 BM25) on 16-query Pilot Benchmark (Engineering Smoke Test)",
        "purpose": "engineering_smoke_test_only",
        "diagnostic_status": "DIAGNOSTIC_ONLY",
        "eligible_for_training": False,
        "source_partition": "frozen_test",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_queries": n_total,
        "corpus_chunks_indexed": chunk_count,
        "retrieval_engine": "SQLite FTS5 BM25 (k1=1.2, b=0.75, unicode61)",
        "overall_metrics": {
            "recall_at_1": float(sum(recalls_1) / n_total),
            "recall_at_5": float(sum(recalls_5) / n_total),
            "recall_at_10": float(sum(recalls_10) / n_total),
            "recall_at_20": float(sum(recalls_20) / n_total),
            "mrr_at_10": float(sum(mrrs_10) / n_total),
            "ndcg_at_10": float(sum(ndcgs_10) / n_total),
        },
        "latency_telemetry": telemetry,
        "failure_analysis": {
            "total_failures_top10": len(failures),
            "failure_rate_top10": float(len(failures) / n_total),
            "failures_top50": sum(1 for f in failures if f["failure_type"] == "RETRIEVAL_FAILURE_TOP50"),
        },
        "domain_breakdown": domain_summary,
        "per_query_results": per_query_results,
    }

    # 6. Save artifacts
    Path(predictions_output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(predictions_output_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")
    print(f"Saved predictions to: {predictions_output_path}")

    with open(failures_output_path, "w", encoding="utf-8") as f:
        for fl in failures:
            f.write(json.dumps(fl) + "\n")
    print(f"Saved failure triage to: {failures_output_path}")

    with open(metrics_output_path, "w", encoding="utf-8") as f:
        json.dump(aggregate_summary, f, indent=2)
    print(f"Saved aggregate metrics to: {metrics_output_path}")

    print("\n" + "=" * 70)
    print("E0-PILOT BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"Recall@1:   {aggregate_summary['overall_metrics']['recall_at_1']:.4f}")
    print(f"Recall@5:   {aggregate_summary['overall_metrics']['recall_at_5']:.4f}")
    print(f"Recall@10:  {aggregate_summary['overall_metrics']['recall_at_10']:.4f}")
    print(f"Recall@20:  {aggregate_summary['overall_metrics']['recall_at_20']:.4f}")
    print(f"MRR@10:     {aggregate_summary['overall_metrics']['mrr_at_10']:.4f}")
    print(f"NDCG@10:    {aggregate_summary['overall_metrics']['ndcg_at_10']:.4f}")
    print(f"QPS:        {telemetry['queries_per_sec']:.1f}")
    print(f"Mean Lat:   {telemetry['mean_latency_ms']:.2f} ms")
    print(f"Failures:   {len(failures)} / {n_total} queries ({aggregate_summary['failure_analysis']['failure_rate_top10']*100:.1f}%)")
    print("=" * 70)

    return aggregate_summary


if __name__ == "__main__":
    run_e0_pilot()
