"""Run E0-v0 Formal Lexical Baseline on Benchmark v0 (Development Benchmark, N=140).

Executes SQLite FTS5 BM25 retrieval over the complete frozen corpus (11,645 chunks)
for the 140 development benchmark queries. Computes IR metrics, detailed multidimensional
aggregations (domain, typology, provenance), latency distribution (p50/p95/p99), and failure triage.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List

import numpy as np

from ragtune.evaluation.metrics import mrr_at_k, ndcg_at_k, recall_at_k
from ragtune.retrieval.lexical_retriever import SQLiteLexicalRetriever
from ragtune.training.guardrails import validate_validation_query


def get_git_commit_sha() -> str:
    """Retrieve current Git commit SHA."""
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return out
    except Exception:
        return "UNKNOWN"


def run_e0_v0(
    corpus_chunks_path: str = "data/processed/corpus_chunks.jsonl",
    benchmark_path: str = "benchmarks/benchmark_v0.jsonl",
    db_path: str = "data/indices/sqlite_fts.db",
    manifest_path: str = "benchmarks/e0_v0_manifest.json",
    predictions_path: str = "benchmarks/e0_v0_predictions.jsonl",
    failures_path: str = "benchmarks/e0_v0_failures.jsonl",
    metrics_path: str = "benchmarks/e0_v0_metrics.json",
    top_k: int = 50,
) -> Dict[str, Any]:
    print("=" * 70)
    print("RAGTUNE EXPERIMENT E0-v0: FORMAL LEXICAL BASELINE (Benchmark v0, N=140)")
    print("=" * 70)

    # 1. Load benchmark and validate partition guardrails
    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    print(f"Loaded {len(queries)} queries from {benchmark_path}.")

    for q in queries:
        validate_validation_query(q)
    print("Guardrail assertion passed: all 140 queries verified as validation partition.")

    # 2. Initialize retriever
    retriever = SQLiteLexicalRetriever(db_path=db_path)
    chunk_count = retriever.build_index(corpus_chunks_path, overwrite=False)
    print(f"Index verified with {chunk_count} corpus chunks.")

    # 3. Execute batch retrieval
    print(f"Executing retrieval for {len(queries)} queries (top_k={top_k})...")
    predictions, timing_telemetry = retriever.search_batch(queries, top_k=top_k)

    latencies = [p["latency_ms"] for p in predictions]
    p50_lat = float(np.percentile(latencies, 50))
    p95_lat = float(np.percentile(latencies, 95))
    p99_lat = float(np.percentile(latencies, 99))
    mean_lat = float(np.mean(latencies))

    latency_telemetry = {
        "total_queries": len(queries),
        "total_elapsed_sec": timing_telemetry["total_elapsed_sec"],
        "queries_per_sec": timing_telemetry["queries_per_sec"],
        "mean_latency_ms": mean_lat,
        "p50_latency_ms": p50_lat,
        "p95_latency_ms": p95_lat,
        "p99_latency_ms": p99_lat,
    }

    # 4. Evaluation and Multidimensional Aggregations
    overall_r1: List[float] = []
    overall_r5: List[float] = []
    overall_r10: List[float] = []
    overall_r20: List[float] = []
    overall_mrr10: List[float] = []
    overall_ndcg10: List[float] = []

    group_stats: Dict[str, Dict[str, Dict[str, List[float]]]] = {
        "domain": {},
        "typology": {},
        "provenance": {},
    }

    failures = []
    per_query_results = []

    for q, p in zip(queries, predictions):
        domain = q["domain"]
        typology = q["typology"]
        provenance = q["provenance_type"]
        qid = q["query_id"]

        # Ensure group buckets exist
        for g_type, g_val in [("domain", domain), ("typology", typology), ("provenance", provenance)]:
            if g_val not in group_stats[g_type]:
                group_stats[g_type][g_val] = {
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

        overall_r1.append(r1)
        overall_r5.append(r5)
        overall_r10.append(r10)
        overall_r20.append(r20)
        overall_mrr10.append(mrr)
        overall_ndcg10.append(ndcg)

        for g_type, g_val in [("domain", domain), ("typology", typology), ("provenance", provenance)]:
            group_stats[g_type][g_val]["r1"].append(r1)
            group_stats[g_type][g_val]["r5"].append(r5)
            group_stats[g_type][g_val]["r10"].append(r10)
            group_stats[g_type][g_val]["r20"].append(r20)
            group_stats[g_type][g_val]["mrr10"].append(mrr)
            group_stats[g_type][g_val]["ndcg10"].append(ndcg)

        hits_50 = [cid for cid in retrieved[:50] if cid in positives]
        hits_10 = [cid for cid in retrieved[:10] if cid in positives]

        status = "SUCCESS"
        if len(hits_50) == 0:
            status = "RETRIEVAL_FAILURE_TOP50"
        elif len(hits_10) == 0:
            status = "RETRIEVAL_FAILURE_TOP10"

        canonical_rank = retrieved.index(canonical_id) + 1 if (canonical_id and canonical_id in retrieved) else None

        query_eval = {
            "query_id": qid,
            "domain": domain,
            "typology": typology,
            "provenance_type": provenance,
            "query_text": q["query_text"],
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
            "latency_ms": p["latency_ms"],
        }
        per_query_results.append(query_eval)

        if status != "SUCCESS":
            # Categorize failure mechanism
            qtext_lower = q["query_text"].lower()
            if any(term in qtext_lower for term in ["difference", "distinction", "versus", "vs", "compare", "differ"]):
                mechanism = "semantic_fine_grained_distinction"
            elif any(sym in q["query_text"] for sym in [".", "_", "()", "/", "::"]):
                mechanism = "code_syntax_and_identifier_mismatch"
            elif status == "RETRIEVAL_FAILURE_TOP50":
                mechanism = "vocabulary_mismatch_or_sparse_coverage"
            else:
                mechanism = "lexical_term_flooding_by_confusers"

            failures.append({
                "query_id": qid,
                "domain": domain,
                "typology": typology,
                "provenance_type": provenance,
                "query_text": q["query_text"],
                "failure_type": status,
                "failure_mechanism": mechanism,
                "source_partition": "validation",
                "eligible_for_rule_mining": True,
                "eligible_for_direct_training": False,
                "canonical_chunk_id": canonical_id,
                "canonical_rank": canonical_rank,
                "positive_chunk_ids": list(positives),
                "top_5_retrieved": [
                    {"chunk_id": cid, "score": score}
                    for cid, score in zip(retrieved[:5], p["scores"][:5])
                ],
            })

    # Summarize breakdowns
    def summarize_group(d: Dict[str, Dict[str, List[float]]]) -> Dict[str, Any]:
        out = {}
        for k, vals in d.items():
            n = len(vals["r1"])
            out[k] = {
                "query_count": n,
                "recall_at_1": float(np.mean(vals["r1"])),
                "recall_at_5": float(np.mean(vals["r5"])),
                "recall_at_10": float(np.mean(vals["r10"])),
                "recall_at_20": float(np.mean(vals["r20"])),
                "mrr_at_10": float(np.mean(vals["mrr10"])),
                "ndcg_at_10": float(np.mean(vals["ndcg10"])),
            }
        return out

    domain_summary = summarize_group(group_stats["domain"])
    typology_summary = summarize_group(group_stats["typology"])
    provenance_summary = summarize_group(group_stats["provenance"])

    # Failure mechanisms tally
    mech_counts = {}
    for fl in failures:
        m = fl["failure_mechanism"]
        mech_counts[m] = mech_counts.get(m, 0) + 1

    n_total = len(queries)
    aggregate_metrics = {
        "recall_at_1": float(np.mean(overall_r1)),
        "recall_at_5": float(np.mean(overall_r5)),
        "recall_at_10": float(np.mean(overall_r10)),
        "recall_at_20": float(np.mean(overall_r20)),
        "mrr_at_10": float(np.mean(overall_mrr10)),
        "ndcg_at_10": float(np.mean(overall_ndcg10)),
    }

    # 5. Persist Manifest
    git_commit_sha = get_git_commit_sha()
    manifest_data = {
        "experiment_id": "E0-v0",
        "description": "Formal Lexical Baseline (SQLite FTS5 BM25) on Benchmark v0 (Development Benchmark, N=140)",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit_sha": git_commit_sha,
        "corpus_freeze_v0_sha256": "bb366346ec1b7dea9cb61286c435c074f17b88a4dd1ea75dbbdbaab575e13d57",
        "benchmark_v0_sha256": "423420b923c15a74e0125f9a00a5538df175e37c6da3fbe03e103a700d097b2a",
        "benchmark_source_partition": "validation",
        "corpus_chunks_indexed": chunk_count,
        "retrieval_engine": "SQLite FTS5 BM25 (k1=1.2, b=0.75, unicode61)",
        "total_queries": n_total,
        "overall_metrics": aggregate_metrics,
        "latency_telemetry": latency_telemetry,
        "failure_summary": {
            "total_failures_top10": len(failures),
            "failure_rate_top10": float(len(failures) / n_total),
            "failures_top50": sum(1 for f in failures if f["failure_type"] == "RETRIEVAL_FAILURE_TOP50"),
            "failure_mechanisms": mech_counts,
        },
    }

    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"Saved manifest to: {manifest_path}")

    # 6. Persist Predictions
    with open(predictions_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")
    print(f"Saved predictions to: {predictions_path}")

    # 7. Persist Failures
    with open(failures_path, "w", encoding="utf-8") as f:
        for fl in failures:
            f.write(json.dumps(fl) + "\n")
    print(f"Saved failure triage to: {failures_path}")

    # 8. Persist Full Metrics Report
    full_metrics_report = {
        "experiment_id": "E0-v0",
        "timestamp_utc": manifest_data["timestamp_utc"],
        "git_commit_sha": git_commit_sha,
        "total_queries": n_total,
        "overall_metrics": aggregate_metrics,
        "domain_breakdown": domain_summary,
        "typology_breakdown": typology_summary,
        "provenance_breakdown": provenance_summary,
        "latency_telemetry": latency_telemetry,
        "failure_analysis": {
            "total_failures_top10": len(failures),
            "failure_rate_top10": float(len(failures) / n_total),
            "failures_top50": sum(1 for f in failures if f["failure_type"] == "RETRIEVAL_FAILURE_TOP50"),
            "mechanisms": mech_counts,
        },
        "per_query_results": per_query_results,
    }
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(full_metrics_report, f, indent=2)
    print(f"Saved full metrics report to: {metrics_path}")

    print("\n" + "=" * 70)
    print("E0-v0 BENCHMARK SUMMARY (N=140)")
    print("=" * 70)
    print(f"Recall@1:   {aggregate_metrics['recall_at_1']:.4f}")
    print(f"Recall@5:   {aggregate_metrics['recall_at_5']:.4f}")
    print(f"Recall@10:  {aggregate_metrics['recall_at_10']:.4f}")
    print(f"Recall@20:  {aggregate_metrics['recall_at_20']:.4f}")
    print(f"MRR@10:     {aggregate_metrics['mrr_at_10']:.4f}")
    print(f"NDCG@10:    {aggregate_metrics['ndcg_at_10']:.4f}")
    print(f"QPS:        {latency_telemetry['queries_per_sec']:.1f}")
    print(f"Mean Lat:   {latency_telemetry['mean_latency_ms']:.2f} ms")
    print(f"P50 Lat:    {latency_telemetry['p50_latency_ms']:.2f} ms")
    print(f"P95 Lat:    {latency_telemetry['p95_latency_ms']:.2f} ms")
    print(f"P99 Lat:    {latency_telemetry['p99_latency_ms']:.2f} ms")
    print(f"Failures:   {len(failures)} / {n_total} queries ({len(failures)/n_total*100:.1f}%)")
    print("=" * 70)

    return full_metrics_report


if __name__ == "__main__":
    run_e0_v0()
