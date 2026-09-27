"""Run Provisional Stage-2 Reranker Baselines on Candidate Benchmark v0.

Model: BAAI/bge-reranker-base (cross-encoder).
Evaluates zero-shot reranking on:
1. E2b-Hybrid: Reranks top-50 from E2a (BM25 + BGE-small RRF)
2. E2b-BM25: Reranks top-50 from E0 (SQLite BM25)
Persists predictions, metrics, failures, and manifests labeled PROVISIONAL_PENDING_HUMAN_REVIEW.
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
from ragtune.retrieval.cross_encoder_reranker import CrossEncoderReranker
from ragtune.retrieval.dense_retriever import format_chunk_text
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


def load_corpus_dict(corpus_path: str = "data/processed/corpus_chunks.jsonl") -> Dict[str, str]:
    """Load corpus chunks into a {chunk_id: formatted_text} dictionary."""
    print(f"Loading corpus texts from {corpus_path}...")
    corpus_dict = {}
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            corpus_dict[d["chunk_id"]] = format_chunk_text(d, include_breadcrumb=True)
    print(f"Loaded {len(corpus_dict)} corpus chunk texts.")
    return corpus_dict


def evaluate_reranked(
    queries: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    experiment_id: str,
    description: str,
    manifest_path: str,
    predictions_path: str,
    failures_path: str,
    metrics_path: str,
    stage1_info: Dict[str, Any],
) -> Dict[str, Any]:
    git_sha = get_git_commit_sha()
    bench_hash = compute_file_sha256("benchmarks/benchmark_v0.jsonl")
    corpus_hash = compute_file_sha256("data/processed/corpus_chunks.jsonl")

    latencies = [p["latency_ms"] for p in predictions]
    p50_lat = float(np.percentile(latencies, 50))
    p95_lat = float(np.percentile(latencies, 95))
    p99_lat = float(np.percentile(latencies, 99))
    mean_lat = float(np.mean(latencies))
    total_elapsed = sum(latencies) / 1000.0

    peak_vram_mb = 0.0
    if torch.cuda.is_available():
        peak_vram_mb = float(torch.cuda.max_memory_allocated() / (1024 * 1024))

    latency_telemetry = {
        "total_queries": len(queries),
        "total_elapsed_sec": total_elapsed,
        "queries_per_sec": float(len(queries) / total_elapsed) if total_elapsed > 0 else 0.0,
        "mean_latency_ms": mean_lat,
        "p50_latency_ms": p50_lat,
        "p95_latency_ms": p95_lat,
        "p99_latency_ms": p99_lat,
        "peak_vram_allocated_mb": peak_vram_mb,
    }

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
                mechanism = "stage1_pool_miss"
            else:
                mechanism = "cross_encoder_misranking"

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

    manifest_data = {
        "experiment_id": experiment_id,
        "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
        "canonical_status": "NOT_FROZEN",
        "description": description,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit_sha": git_sha,
        "reranker_model": "BAAI/bge-reranker-base",
        "reranker_exact_commit_sha": "2cfc18c9415c912f9d8155881c133215df768a70",
        "stage1_info": stage1_info,
        "corpus_chunks_path": "data/processed/corpus_chunks.jsonl",
        "corpus_chunks_sha256": corpus_hash,
        "benchmark_v0_path": "benchmarks/benchmark_v0.jsonl",
        "benchmark_v0_sha256": bench_hash,
        "benchmark_source_partition": "validation",
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

    Path(predictions_path).parent.mkdir(parents=True, exist_ok=True)
    with open(predictions_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")

    Path(failures_path).parent.mkdir(parents=True, exist_ok=True)
    with open(failures_path, "w", encoding="utf-8") as f:
        for fl in failures:
            f.write(json.dumps(fl) + "\n")

    full_metrics_report = {
        "experiment_id": experiment_id,
        "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
        "canonical_status": "NOT_FROZEN",
        "timestamp_utc": manifest_data["timestamp_utc"],
        "git_commit_sha": git_sha,
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

    print("\n" + "=" * 75)
    print(f"{experiment_id} BENCHMARK SUMMARY (N={n_total})")
    print("Status: PROVISIONAL_PENDING_HUMAN_REVIEW")
    print("=" * 75)
    print(f"Recall@1:   {aggregate_metrics['recall_at_1']:.4f}")
    print(f"Recall@5:   {aggregate_metrics['recall_at_5']:.4f}")
    print(f"Recall@10:  {aggregate_metrics['recall_at_10']:.4f}")
    print(f"Recall@20:  {aggregate_metrics['recall_at_20']:.4f}")
    print(f"MRR@10:     {aggregate_metrics['mrr_at_10']:.4f}")
    print(f"NDCG@10:    {aggregate_metrics['ndcg_at_10']:.4f}")
    print(f"Mean Lat:   {latency_telemetry['mean_latency_ms']:.2f} ms")
    print(f"P50 Lat:    {latency_telemetry['p50_latency_ms']:.2f} ms")
    print(f"P95 Lat:    {latency_telemetry['p95_latency_ms']:.2f} ms")
    print(f"P99 Lat:    {latency_telemetry['p99_latency_ms']:.2f} ms")
    print(f"Peak VRAM:  {latency_telemetry['peak_vram_allocated_mb']:.1f} MB")
    print(f"Failures:   {len(failures)} / {n_total} queries ({len(failures)/n_total*100:.1f}%)")
    print("=" * 75)

    return full_metrics_report


def run_reranking():
    # 1. Load benchmark & validate guardrails
    benchmark_path = "benchmarks/benchmark_v0.jsonl"
    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    for q in queries:
        validate_validation_query(q)

    # 2. Load corpus texts
    corpus_dict = load_corpus_dict()

    # 3. Load Stage 1 predictions
    with open("benchmarks/experiments/e2a_rrf_bge_candidate_predictions.jsonl", "r", encoding="utf-8") as f:
        preds_hybrid = [json.loads(line) for line in f]

    with open("benchmarks/experiments/e0_v0_candidate_predictions.jsonl", "r", encoding="utf-8") as f:
        preds_e0 = [json.loads(line) for line in f]

    # 4. Initialize Reranker
    reranker = CrossEncoderReranker(
        model_name="BAAI/bge-reranker-base",
        batch_size=16,
        max_length=512,
    )

    # Rerank E2a (Hybrid) top-50
    print("\n>>> Executing Stage-2 Reranking on E2a (Hybrid BM25+BGE Top-50)...")
    reranked_preds_hybrid, _ = reranker.rerank_batch(
        queries=queries,
        stage1_predictions=preds_hybrid,
        chunk_texts=corpus_dict,
        top_k=50,
    )
    evaluate_reranked(
        queries=queries,
        predictions=reranked_preds_hybrid,
        experiment_id="E2b-Reranker-Hybrid-v0-candidate",
        description="Stage-2 Cross-Encoder Reranker (BAAI/bge-reranker-base) on E2a Hybrid Top-50",
        manifest_path="benchmarks/experiments/e2b_reranker_hybrid_candidate_manifest.json",
        predictions_path="benchmarks/experiments/e2b_reranker_hybrid_candidate_predictions.jsonl",
        failures_path="benchmarks/experiments/e2b_reranker_hybrid_candidate_failures.jsonl",
        metrics_path="benchmarks/experiments/e2b_reranker_hybrid_candidate_metrics.json",
        stage1_info={"stage1_id": "E2a-Hybrid-BGE-v0-candidate", "reranked_depth": 50},
    )

    # Rerank E0 (BM25) top-50
    print("\n>>> Executing Stage-2 Reranking on E0 (BM25 Top-50)...")
    reranked_preds_bm25, _ = reranker.rerank_batch(
        queries=queries,
        stage1_predictions=preds_e0,
        chunk_texts=corpus_dict,
        top_k=50,
    )
    evaluate_reranked(
        queries=queries,
        predictions=reranked_preds_bm25,
        experiment_id="E2b-Reranker-BM25-v0-candidate",
        description="Stage-2 Cross-Encoder Reranker (BAAI/bge-reranker-base) on E0 BM25 Top-50",
        manifest_path="benchmarks/experiments/e2b_reranker_bm25_candidate_manifest.json",
        predictions_path="benchmarks/experiments/e2b_reranker_bm25_candidate_predictions.jsonl",
        failures_path="benchmarks/experiments/e2b_reranker_bm25_candidate_failures.jsonl",
        metrics_path="benchmarks/experiments/e2b_reranker_bm25_candidate_metrics.json",
        stage1_info={"stage1_id": "E0-v0-candidate", "reranked_depth": 50},
    )


if __name__ == "__main__":
    run_reranking()
