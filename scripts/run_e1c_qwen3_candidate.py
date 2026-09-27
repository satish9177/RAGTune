"""Run Provisional E1c Dense Reference Baseline (E1c-Qwen3-v0-candidate) on Candidate Benchmark v0.

Model: Qwen/Qwen3-Embedding-0.6B (dimension: 1024, L2 normalized).
Evaluates zero-shot dense retrieval over the frozen corpus (11,645 chunks) on 140 candidate development benchmark queries.
Persists predictions, metrics, failures, and manifest labeled PROVISIONAL_PENDING_HUMAN_REVIEW.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List

import numpy as np
import torch

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.evaluation.metrics import mrr_at_k, ndcg_at_k, recall_at_k
from ragtune.retrieval.dense_retriever import DenseRetriever
from ragtune.training.guardrails import validate_validation_query


def get_git_commit_sha() -> str:
    """Retrieve current Git commit SHA."""
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return out
    except Exception:
        return "UNKNOWN"


def compute_file_sha256(path: Path | str) -> str:
    """Compute exact SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_e1c_qwen3_candidate(
    model_name: str = "Qwen/Qwen3-Embedding-0.6B",
    corpus_chunks_path: str = "data/processed/corpus_chunks.jsonl",
    benchmark_path: str = "benchmarks/benchmark_v0.jsonl",
    cache_dir: str = "data/indices",
    manifest_path: str = "benchmarks/experiments/e1c_qwen3_candidate_manifest.json",
    predictions_path: str = "benchmarks/experiments/e1c_qwen3_candidate_predictions.jsonl",
    failures_path: str = "benchmarks/experiments/e1c_qwen3_candidate_failures.jsonl",
    metrics_path: str = "benchmarks/experiments/e1c_qwen3_candidate_metrics.json",
    top_k: int = 50,
    batch_size: int = 32,
) -> Dict[str, Any]:
    print("=" * 75)
    print("RAGTUNE EXPERIMENT E1c-Qwen3-v0-candidate: PROVISIONAL DENSE REFERENCE (N=140)")
    print(f"Model: {model_name} (L2 normalized, 1024-dim)")
    print("Status: PROVISIONAL_PENDING_HUMAN_REVIEW (Canonical Freeze: NOT_FROZEN)")
    print("=" * 75)

    corpus_hash = compute_file_sha256(corpus_chunks_path)
    bench_hash = compute_file_sha256(benchmark_path)
    git_sha = get_git_commit_sha()

    # 1. Load benchmark and validate partition guardrails
    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    print(f"Loaded {len(queries)} queries from {benchmark_path}.")

    for q in queries:
        validate_validation_query(q)
    print("Guardrail assertion passed: all 140 queries verified as validation partition.")

    # 2. Reset CUDA stats and initialize retriever
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    retriever = DenseRetriever(
        model_name_or_path=model_name,
        batch_size=batch_size,
        query_instruction="Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
        precision="float16",
    )
    chunk_count = retriever.build_index(corpus_chunks_path, cache_dir=cache_dir, overwrite=False)
    print(f"Dense index ready with {chunk_count} corpus chunks.")

    # 3. Measure query-by-query latency distribution
    print(f"Executing retrieval for {len(queries)} queries (top_k={top_k})...")
    individual_latencies: List[float] = []
    predictions: List[Dict[str, Any]] = []

    t_batch_start = time.perf_counter()
    for q in queries:
        retrieved_ids, scores, lat_ms = retriever.search(
            query_text=q["query_text"],
            top_k=top_k,
            use_instruction=True,
        )
        individual_latencies.append(lat_ms)
        predictions.append({
            "query_id": q["query_id"],
            "retrieved_chunk_ids": retrieved_ids,
            "scores": scores,
            "latency_ms": lat_ms,
        })
    total_batch_elapsed = time.perf_counter() - t_batch_start

    p50_lat = float(np.percentile(individual_latencies, 50))
    p95_lat = float(np.percentile(individual_latencies, 95))
    p99_lat = float(np.percentile(individual_latencies, 99))
    mean_lat = float(np.mean(individual_latencies))
    qps = float(len(queries) / total_batch_elapsed)

    peak_vram_mb = 0.0
    if torch.cuda.is_available():
        peak_vram_mb = float(torch.cuda.max_memory_allocated() / (1024 * 1024))

    latency_telemetry = {
        "total_queries": len(queries),
        "total_elapsed_sec": total_batch_elapsed,
        "queries_per_sec": qps,
        "mean_latency_ms": mean_lat,
        "p50_latency_ms": p50_lat,
        "p95_latency_ms": p95_lat,
        "p99_latency_ms": p99_lat,
        "peak_vram_allocated_mb": peak_vram_mb,
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
            qtext_lower = q["query_text"].lower()
            if any(term in qtext_lower for term in ["difference", "distinction", "versus", "vs", "compare", "differ"]):
                mechanism = "semantic_fine_grained_distinction"
            elif any(sym in q["query_text"] for sym in [".", "_", "()", "/", "::"]):
                mechanism = "code_syntax_and_identifier_mismatch"
            elif status == "RETRIEVAL_FAILURE_TOP50":
                mechanism = "dense_embedding_drift_or_sparse_semantic_signal"
            else:
                mechanism = "dense_semantic_confuser_crowding"

            failures.append({
                "query_id": qid,
                "domain": domain,
                "typology": typology,
                "provenance_type": provenance,
                "query_text": q["query_text"],
                "failure_type": status,
                "failure_mechanism": mechanism,
                "source_partition": "validation",
                "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
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

    mech_counts: Dict[str, int] = {}
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
    manifest_data = {
        "experiment_id": "E1c-Qwen3-v0-candidate",
        "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
        "canonical_status": "NOT_FROZEN",
        "description": "Provisional Dense Reference Baseline (Qwen/Qwen3-Embedding-0.6B) on Candidate Benchmark v0 (N=140)",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit_sha": git_sha,
        "model_id": model_name,
        "model_exact_commit_sha": "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        "embedding_dimension": 1024,
        "normalization": "l2",
        "query_instruction_prefix": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
        "corpus_chunks_path": corpus_chunks_path,
        "corpus_chunks_sha256": corpus_hash,
        "benchmark_v0_path": benchmark_path,
        "benchmark_v0_sha256": bench_hash,
        "benchmark_source_partition": "validation",
        "corpus_chunks_indexed": chunk_count,
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
    Path(predictions_path).parent.mkdir(parents=True, exist_ok=True)
    with open(predictions_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")
    print(f"Saved predictions to: {predictions_path}")

    # 7. Persist Failures
    Path(failures_path).parent.mkdir(parents=True, exist_ok=True)
    with open(failures_path, "w", encoding="utf-8") as f:
        for fl in failures:
            f.write(json.dumps(fl) + "\n")
    print(f"Saved failure triage to: {failures_path}")

    # 8. Persist Full Metrics Report
    full_metrics_report = {
        "experiment_id": "E1c-Qwen3-v0-candidate",
        "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
        "canonical_status": "NOT_FROZEN",
        "timestamp_utc": manifest_data["timestamp_utc"],
        "git_commit_sha": git_sha,
        "model_id": model_name,
        "embedding_dimension": 1024,
        "corpus_chunks_sha256": corpus_hash,
        "benchmark_v0_sha256": bench_hash,
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
    Path(metrics_path).parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(full_metrics_report, f, indent=2)
    print(f"Saved full metrics report to: {metrics_path}")

    print("\n" + "=" * 75)
    print("E1c-Qwen3-v0-candidate BENCHMARK SUMMARY (N=140)")
    print("Status: PROVISIONAL_PENDING_HUMAN_REVIEW")
    print("=" * 75)
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
    print(f"Peak VRAM:  {latency_telemetry['peak_vram_allocated_mb']:.1f} MB")
    print(f"Failures:   {len(failures)} / {n_total} queries ({len(failures)/n_total*100:.1f}%)")
    print("=" * 75)

    return full_metrics_report


if __name__ == "__main__":
    run_e1c_qwen3_candidate()
