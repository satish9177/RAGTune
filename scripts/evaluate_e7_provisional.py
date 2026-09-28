"""Evaluate provisional E7 domain reranker on Benchmark v0 Development split.

Protocol:
- Stage-1 candidate pool: E5C (BM25 + Matched-Easy Dense RRF k=60)
- Candidate depth: Top-20
- Model: data/models/e7_bge_reranker_provisional_v0
- Evaluation split: Benchmark v0 Development (140 queries grounded in validation partition)
- Strictly ZERO access to frozen_test or unconsumed test splits
- Paired 10,000 BCa bootstrap vs E5C Stage-1 and vs E6C-Top20 Generic Reranker
- Edwards continuity-corrected McNemar test
- Comprehensive failure transition analysis
- Latency and VRAM profiling
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import scipy.stats
from sentence_transformers import CrossEncoder
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.evaluation.metrics import dcg_at_k, mrr_at_k, ndcg_at_k, recall_at_k
from ragtune.retrieval.dense_retriever import format_chunk_text
from ragtune.training.guardrails import validate_validation_query


def compute_file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_bca_bootstrap_ci(
    cand_scores: List[float] | np.ndarray,
    base_scores: List[float] | np.ndarray,
    n_resamples: int = 10000,
    seed: int = 42,
) -> Tuple[float, float, float]:
    diffs = np.array(cand_scores, dtype=np.float64) - np.array(base_scores, dtype=np.float64)
    mean_diff = float(np.mean(diffs))

    if np.all(diffs == diffs[0]):
        return mean_diff, mean_diff, mean_diff

    try:
        res = scipy.stats.bootstrap(
            (diffs,),
            statistic=np.mean,
            n_resamples=n_resamples,
            confidence_level=0.95,
            method="BCa",
            random_state=seed,
        )
        ci_low = float(res.confidence_interval.low)
        ci_high = float(res.confidence_interval.high)
    except Exception:
        res = scipy.stats.bootstrap(
            (diffs,),
            statistic=np.mean,
            n_resamples=n_resamples,
            confidence_level=0.95,
            method="percentile",
            random_state=seed,
        )
        ci_low = float(res.confidence_interval.low)
        ci_high = float(res.confidence_interval.high)

    return mean_diff, ci_low, ci_high


def compute_mcnemar_test(
    hits_cand: List[bool] | np.ndarray,
    hits_base: List[bool] | np.ndarray,
) -> Dict[str, Any]:
    n01 = int(sum(1 for c, b in zip(hits_cand, hits_base) if c and not b))
    n10 = int(sum(1 for c, b in zip(hits_cand, hits_base) if not c and b))
    n00 = int(sum(1 for c, b in zip(hits_cand, hits_base) if not c and not b))
    n11 = int(sum(1 for c, b in zip(hits_cand, hits_base) if c and b))

    discordant = n01 + n10
    if discordant == 0:
        return {
            "candidate_wins": n01,
            "candidate_losses": n10,
            "both_hit": n11,
            "both_miss": n00,
            "chi2_stat": 0.0,
            "p_value": 1.0,
            "raw_p_value": 1.0,
            "reporting": "McNemar p=1.0000 (unadjusted)",
        }

    stat = (abs(n01 - n10) - 1.0) ** 2 / discordant
    p_val = float(1.0 - scipy.stats.chi2.cdf(stat, df=1))

    return {
        "candidate_wins": n01,
        "candidate_losses": n10,
        "both_hit": n11,
        "both_miss": n00,
        "chi2_stat": float(stat),
        "p_value": p_val,
        "raw_p_value": p_val,
        "reporting": f"McNemar p={p_val:.4f} (unadjusted)",
    }


def evaluate_reranked_predictions(
    benchmark_queries: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    pred_map = {p["query_id"]: p for p in predictions}

    r1_list, r5_list, r10_list, r20_list, r50_list = [], [], [], [], []
    hr1_list, hr5_list, hr10_list, hr20_list, hr50_list = [], [], [], [], []
    mrr10_list, ndcg10_list = [], []
    top10_failures: List[Dict[str, Any]] = []

    domain_stats: Dict[str, Dict[str, List[float]]] = {}
    typology_stats: Dict[str, Dict[str, List[float]]] = {}
    per_query_results: List[Dict[str, Any]] = []

    for q in benchmark_queries:
        qid = q["query_id"]
        p = pred_map[qid]
        retrieved_ids = p["retrieved_chunk_ids"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}

        r1 = recall_at_k(retrieved_ids, positives, k=1)
        r5 = recall_at_k(retrieved_ids, positives, k=5)
        r10 = recall_at_k(retrieved_ids, positives, k=10)
        r20 = recall_at_k(retrieved_ids, positives, k=20)
        r50 = recall_at_k(retrieved_ids, positives, k=50)

        hr1 = 1.0 if any(cid in positives for cid in retrieved_ids[:1]) else 0.0
        hr5 = 1.0 if any(cid in positives for cid in retrieved_ids[:5]) else 0.0
        hr10 = 1.0 if any(cid in positives for cid in retrieved_ids[:10]) else 0.0
        hr20 = 1.0 if any(cid in positives for cid in retrieved_ids[:20]) else 0.0
        hr50 = 1.0 if any(cid in positives for cid in retrieved_ids[:50]) else 0.0

        mrr10 = mrr_at_k(retrieved_ids, positives, k=10)
        ndcg10 = ndcg_at_k(retrieved_ids, graded_rel, k=10)
        has_hit10 = hr10 == 1.0

        r1_list.append(r1)
        r5_list.append(r5)
        r10_list.append(r10)
        r20_list.append(r20)
        r50_list.append(r50)

        hr1_list.append(hr1)
        hr5_list.append(hr5)
        hr10_list.append(hr10)
        hr20_list.append(hr20)
        hr50_list.append(hr50)

        mrr10_list.append(mrr10)
        ndcg10_list.append(ndcg10)

        if not has_hit10:
            first_rank = next((idx for idx, cid in enumerate(retrieved_ids, start=1) if cid in positives), None)
            top10_failures.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q.get("typology", "direct_lookup"),
                "query_text": q["query_text"],
                "first_hit_rank": first_rank,
            })

        for key, store in [(q["domain"], domain_stats), (q.get("typology", "direct_lookup"), typology_stats)]:
            if key not in store:
                store[key] = {"r10": [], "hr10": [], "mrr10": [], "ndcg10": []}
            store[key]["r10"].append(r10)
            store[key]["hr10"].append(hr10)
            store[key]["mrr10"].append(mrr10)
            store[key]["ndcg10"].append(ndcg10)

        per_query_results.append({
            "query_id": qid,
            "r10": r10,
            "hr10": hr10,
            "ndcg10": ndcg10,
            "mrr10": mrr10,
            "has_hit10": has_hit10,
            "retrieved_top10": retrieved_ids[:10],
        })

    overall_metrics = {
        "recall_at_1": float(np.mean(r1_list)),
        "recall_at_5": float(np.mean(r5_list)),
        "recall_at_10": float(np.mean(r10_list)),
        "recall_at_20": float(np.mean(r20_list)),
        "recall_at_50": float(np.mean(r50_list)),
        "hit_rate_at_1": float(np.mean(hr1_list)),
        "hit_rate_at_5": float(np.mean(hr5_list)),
        "hit_rate_at_10": float(np.mean(hr10_list)),
        "hit_rate_at_20": float(np.mean(hr20_list)),
        "hit_rate_at_50": float(np.mean(hr50_list)),
        "mrr_at_10": float(np.mean(mrr10_list)),
        "ndcg_at_10": float(np.mean(ndcg10_list)),
        "top10_failures": len(top10_failures),
        "failure_rate": float(len(top10_failures) / len(benchmark_queries)),
    }

    domain_breakdown = {
        d: {
            "recall_at_10": float(np.mean(vals["r10"])),
            "hit_rate_at_10": float(np.mean(vals["hr10"])),
            "mrr_at_10": float(np.mean(vals["mrr10"])),
            "ndcg_at_10": float(np.mean(vals["ndcg10"])),
            "query_count": len(vals["r10"]),
        }
        for d, vals in sorted(domain_stats.items())
    }

    typology_breakdown = {
        t: {
            "recall_at_10": float(np.mean(vals["r10"])),
            "hit_rate_at_10": float(np.mean(vals["hr10"])),
            "mrr_at_10": float(np.mean(vals["mrr10"])),
            "ndcg_at_10": float(np.mean(vals["ndcg10"])),
            "query_count": len(vals["r10"]),
        }
        for t, vals in sorted(typology_stats.items())
    }

    return overall_metrics, domain_breakdown, typology_breakdown, per_query_results


def main():
    root = Path(__file__).resolve().parent.parent
    benchmark_path = root / "benchmarks" / "benchmark_v0.jsonl"
    corpus_chunks_path = root / "data" / "processed" / "corpus_chunks.jsonl"
    e5c_preds_path = root / "benchmarks" / "experiments" / "e5c_hybrid_matchedeasy_predictions.jsonl"
    e6c_top20_preds_path = root / "benchmarks" / "experiments" / "e6c_top20_predictions.jsonl"
    model_dir = root / "data" / "models" / "e7_bge_reranker_provisional_v0"

    out_preds_path = root / "benchmarks" / "experiments" / "e7c_provisional_predictions.jsonl"
    out_metrics_path = root / "benchmarks" / "experiments" / "e7c_provisional_metrics.json"
    out_manifest_path = root / "benchmarks" / "experiments" / "e7c_provisional_manifest.json"
    out_trans_path = root / "benchmarks" / "experiments" / "e7c_failure_transition_analysis.json"

    print("=" * 80)
    print("STARTING PROVISIONAL E7 DOMAIN RERANKER EVALUATION (Depth: Top-20)")
    print("=" * 80)

    benchmark_sha = compute_file_sha256(benchmark_path)
    corpus_sha = compute_file_sha256(corpus_chunks_path)

    # 1. Load benchmark queries
    benchmark_queries: List[Dict[str, Any]] = []
    with open(benchmark_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            validate_validation_query(q)
            benchmark_queries.append(q)
    print(f"Loaded {len(benchmark_queries)} Benchmark v0 queries.")

    # 2. Load corpus chunks lookup
    print("Loading corpus chunks lookup...")
    chunk_by_id: Dict[str, Dict[str, Any]] = {}
    with open(corpus_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            chunk_by_id[c["chunk_id"]] = c
    print(f"Loaded {len(chunk_by_id)} corpus chunks.")

    # 3. Load Stage-1 predictions
    with open(e5c_preds_path, "r", encoding="utf-8") as f:
        e5c_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}
    print(f"Loaded {len(e5c_preds)} Stage-1 E5C candidate sets.")

    # 4. Load trained E7 reranker
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading trained E7 model from {model_dir} on {device}...")
    reranker_model = CrossEncoder(str(model_dir), device=device, max_length=384)

    # 5. Rerank Top-20 candidates
    candidate_depth = 20
    predictions: List[Dict[str, Any]] = []
    reranker_latencies: List[float] = []
    total_latencies: List[float] = []

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t_start_all = time.perf_counter()
    for q in benchmark_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        s1 = e5c_preds[qid]
        s1_ids = s1["retrieved_chunk_ids"]
        s1_lat = s1.get("latency_ms", 35.0)

        # Slice candidate depth
        cands_to_rerank = s1_ids[:candidate_depth]
        tail_cands = s1_ids[candidate_depth:]

        # Build query-passage pairs
        pairs = []
        for cid in cands_to_rerank:
            chunk = chunk_by_id[cid]
            c_text = format_chunk_text(chunk, include_breadcrumb=True)
            pairs.append((qtext, c_text))

        t0 = time.perf_counter()
        scores = reranker_model.predict(
            pairs,
            batch_size=candidate_depth,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        rerank_ms = (time.perf_counter() - t0) * 1000.0

        reranker_latencies.append(rerank_ms)
        tot_ms = s1_lat + rerank_ms
        total_latencies.append(tot_ms)

        scored_cands = sorted(
            zip(cands_to_rerank, [float(s) for s in scores]),
            key=lambda x: x[1],
            reverse=True,
        )
        reranked_ids = [c for c, _ in scored_cands] + tail_cands
        reranked_scores = [s for _, s in scored_cands] + [0.0] * len(tail_cands)

        predictions.append({
            "query_id": qid,
            "raw_stage1_top_k": s1_ids[:candidate_depth],
            "raw_reranker_scores": [float(s) for s in scores],
            "retrieved_chunk_ids": reranked_ids,
            "scores": reranked_scores,
            "rerank_latency_ms": rerank_ms,
            "total_latency_ms": tot_ms,
        })

    total_eval_elapsed = time.perf_counter() - t_start_all
    peak_vram_alloc = float(torch.cuda.max_memory_allocated() / (1024 * 1024)) if torch.cuda.is_available() else 0.0
    peak_vram_res = float(torch.cuda.max_memory_reserved() / (1024 * 1024)) if torch.cuda.is_available() else 0.0

    # Persist predictions
    with open(out_preds_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")
    print(f"Persisted predictions to {out_preds_path.name}.")

    # Evaluate metrics
    overall_m, domain_m, typology_m, per_query_m = evaluate_reranked_predictions(benchmark_queries, predictions)

    latency_telemetry = {
        "rerank_only_p50_ms": float(np.percentile(reranker_latencies, 50)),
        "rerank_only_p95_ms": float(np.percentile(reranker_latencies, 95)),
        "rerank_only_p99_ms": float(np.percentile(reranker_latencies, 99)),
        "rerank_only_mean_ms": float(np.mean(reranker_latencies)),
        "total_end_to_end_p50_ms": float(np.percentile(total_latencies, 50)),
        "total_end_to_end_p95_ms": float(np.percentile(total_latencies, 95)),
        "total_end_to_end_p99_ms": float(np.percentile(total_latencies, 99)),
        "total_end_to_end_mean_ms": float(np.mean(total_latencies)),
        "throughput_queries_per_sec": float(len(benchmark_queries) / total_eval_elapsed),
        "peak_vram_allocated_mb": peak_vram_alloc,
        "peak_vram_reserved_mb": peak_vram_res,
    }

    # 6. Statistical Comparison against Stage-1 E5C
    print("\nComputing Paired 10,000 BCa Bootstrap vs Stage-1 E5C...")
    e7_ndcg = [pq["ndcg10"] for pq in per_query_m]
    e7_r10 = [pq["r10"] for pq in per_query_m]
    e7_mrr10 = [pq["mrr10"] for pq in per_query_m]
    e7_hits = [pq["has_hit10"] for pq in per_query_m]

    # Compute E5C per-query metrics
    e5c_per_query = []
    for q in benchmark_queries:
        qid = q["query_id"]
        ret = e5c_preds[qid]["retrieved_chunk_ids"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}
        e5c_per_query.append({
            "query_id": qid,
            "ndcg10": ndcg_at_k(ret, graded_rel, k=10),
            "r10": recall_at_k(ret, positives, k=10),
            "mrr10": mrr_at_k(ret, positives, k=10),
            "has_hit10": any(cid in positives for cid in ret[:10]),
        })
    e5c_ndcg = [pq["ndcg10"] for pq in e5c_per_query]
    e5c_r10 = [pq["r10"] for pq in e5c_per_query]
    e5c_mrr10 = [pq["mrr10"] for pq in e5c_per_query]
    e5c_hits = [pq["has_hit10"] for pq in e5c_per_query]

    d_ndcg_e5c, ci_l_ndcg_e5c, ci_h_ndcg_e5c = compute_bca_bootstrap_ci(e7_ndcg, e5c_ndcg, n_resamples=10000, seed=42)
    d_r10_e5c, ci_l_r10_e5c, ci_h_r10_e5c = compute_bca_bootstrap_ci(e7_r10, e5c_r10, n_resamples=10000, seed=42)
    d_mrr_e5c, ci_l_mrr_e5c, ci_h_mrr_e5c = compute_bca_bootstrap_ci(e7_mrr10, e5c_mrr10, n_resamples=10000, seed=42)
    mcnemar_e5c = compute_mcnemar_test(e7_hits, e5c_hits)

    # 7. Statistical Comparison against Generic E6C-Top20
    print("Computing Paired 10,000 BCa Bootstrap vs Generic E6C-Top20...")
    with open(e6c_top20_preds_path, "r", encoding="utf-8") as f:
        e6c_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}

    e6c_per_query = []
    for q in benchmark_queries:
        qid = q["query_id"]
        ret = e6c_preds[qid]["retrieved_chunk_ids"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}
        e6c_per_query.append({
            "query_id": qid,
            "ndcg10": ndcg_at_k(ret, graded_rel, k=10),
            "r10": recall_at_k(ret, positives, k=10),
            "mrr10": mrr_at_k(ret, positives, k=10),
            "has_hit10": any(cid in positives for cid in ret[:10]),
        })
    e6c_ndcg = [pq["ndcg10"] for pq in e6c_per_query]
    e6c_r10 = [pq["r10"] for pq in e6c_per_query]
    e6c_mrr10 = [pq["mrr10"] for pq in e6c_per_query]
    e6c_hits = [pq["has_hit10"] for pq in e6c_per_query]

    d_ndcg_e6c, ci_l_ndcg_e6c, ci_h_ndcg_e6c = compute_bca_bootstrap_ci(e7_ndcg, e6c_ndcg, n_resamples=10000, seed=42)
    d_r10_e6c, ci_l_r10_e6c, ci_h_r10_e6c = compute_bca_bootstrap_ci(e7_r10, e6c_r10, n_resamples=10000, seed=42)
    d_mrr_e6c, ci_l_mrr_e6c, ci_h_mrr_e6c = compute_bca_bootstrap_ci(e7_mrr10, e6c_mrr10, n_resamples=10000, seed=42)
    mcnemar_e6c = compute_mcnemar_test(e7_hits, e6c_hits)

    # 8. Failure Transition Analysis
    print("Running Failure Transition Analysis...")
    e7_pred_map = {p["query_id"]: p for p in predictions}
    e5c_pred_map = e5c_preds
    e6c_pred_map = e6c_preds

    improved_vs_e5c, degraded_vs_e5c = [], []
    recovered_misses_vs_e5c, regressed_misses_vs_e5c = [], []
    demoted_in_pool_vs_e5c, unrecoverable_misses = [], []

    improved_vs_e6c, degraded_vs_e6c = [], []
    recovered_misses_vs_e6c, regressed_misses_vs_e6c = [], []

    for q in benchmark_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}
        canonical_cid = next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None)

        s1_ret = e5c_pred_map[qid]["retrieved_chunk_ids"]
        e6_ret = e6c_pred_map[qid]["retrieved_chunk_ids"]
        e7_ret = e7_pred_map[qid]["retrieved_chunk_ids"]

        s1_ndcg = ndcg_at_k(s1_ret, graded_rel, k=10)
        e6_ndcg = ndcg_at_k(e6_ret, graded_rel, k=10)
        e7_ndcg_val = ndcg_at_k(e7_ret, graded_rel, k=10)

        s1_hit = any(cid in positives for cid in s1_ret[:10])
        e6_hit = any(cid in positives for cid in e6_ret[:10])
        e7_hit = any(cid in positives for cid in e7_ret[:10])

        s1_best_rank = next((idx for idx, cid in enumerate(s1_ret, start=1) if cid in positives), None)
        e7_best_rank = next((idx for idx, cid in enumerate(e7_ret, start=1) if cid in positives), None)
        e6_best_rank = next((idx for idx, cid in enumerate(e6_ret, start=1) if cid in positives), None)

        # vs E5C
        if e7_ndcg_val - s1_ndcg > 0.05:
            improved_vs_e5c.append({"query_id": qid, "domain": q["domain"], "delta_ndcg": e7_ndcg_val - s1_ndcg, "s1_rank": s1_best_rank, "e7_rank": e7_best_rank})
        elif e7_ndcg_val - s1_ndcg < -0.05:
            degraded_vs_e5c.append({"query_id": qid, "domain": q["domain"], "delta_ndcg": e7_ndcg_val - s1_ndcg, "s1_rank": s1_best_rank, "e7_rank": e7_best_rank})

        if not s1_hit and e7_hit:
            recovered_misses_vs_e5c.append({"query_id": qid, "domain": q["domain"], "s1_rank": s1_best_rank, "e7_rank": e7_best_rank})
        elif s1_hit and not e7_hit:
            regressed_misses_vs_e5c.append({"query_id": qid, "domain": q["domain"], "s1_rank": s1_best_rank, "e7_rank": e7_best_rank})

        # In-pool demotions vs E5C Top-20
        if s1_best_rank is not None and s1_best_rank <= 20:
            if e7_best_rank is not None and e7_best_rank > 10:
                demoted_in_pool_vs_e5c.append({"query_id": qid, "domain": q["domain"], "s1_rank": s1_best_rank, "e7_rank": e7_best_rank})

        if s1_best_rank is None or s1_best_rank > 20:
            unrecoverable_misses.append({"query_id": qid, "domain": q["domain"], "s1_rank": s1_best_rank})

        # vs E6C
        if e7_ndcg_val - e6_ndcg > 0.05:
            improved_vs_e6c.append({"query_id": qid, "domain": q["domain"], "delta_ndcg": e7_ndcg_val - e6_ndcg, "e6_rank": e6_best_rank, "e7_rank": e7_best_rank})
        elif e7_ndcg_val - e6_ndcg < -0.05:
            degraded_vs_e6c.append({"query_id": qid, "domain": q["domain"], "delta_ndcg": e7_ndcg_val - e6_ndcg, "e6_rank": e6_best_rank, "e7_rank": e7_best_rank})

        if not e6_hit and e7_hit:
            recovered_misses_vs_e6c.append({"query_id": qid, "domain": q["domain"], "e6_rank": e6_best_rank, "e7_rank": e7_best_rank})
        elif e6_hit and not e7_hit:
            regressed_misses_vs_e6c.append({"query_id": qid, "domain": q["domain"], "e6_rank": e6_best_rank, "e7_rank": e7_best_rank})

    failure_transition_payload = {
        "comparison_e7_vs_e5c": {
            "recovered_misses_count": len(recovered_misses_vs_e5c),
            "recovered_misses": recovered_misses_vs_e5c,
            "regressed_misses_count": len(regressed_misses_vs_e5c),
            "regressed_misses": regressed_misses_vs_e5c,
            "improved_ndcg_count": len(improved_vs_e5c),
            "degraded_ndcg_count": len(degraded_vs_e5c),
            "demoted_in_pool_count": len(demoted_in_pool_vs_e5c),
            "demoted_in_pool": demoted_in_pool_vs_e5c,
            "unrecoverable_misses_count": len(unrecoverable_misses),
        },
        "comparison_e7_vs_e6c_top20": {
            "recovered_misses_count": len(recovered_misses_vs_e6c),
            "recovered_misses": recovered_misses_vs_e6c,
            "regressed_misses_count": len(regressed_misses_vs_e6c),
            "regressed_misses": regressed_misses_vs_e6c,
            "improved_ndcg_count": len(improved_vs_e6c),
            "degraded_ndcg_count": len(degraded_vs_e6c),
        },
    }

    with open(out_trans_path, "w", encoding="utf-8") as f:
        json.dump(failure_transition_payload, f, indent=2)
    print(f"Persisted failure transition analysis to {out_trans_path.name}.")

    # 9. Persist Metrics and Manifest
    statistical_tests = {
        "vs_e5c_stage1": {
            "delta_ndcg10": {
                "mean": d_ndcg_e5c,
                "ci_95_bca_lower": ci_l_ndcg_e5c,
                "ci_95_bca_upper": ci_h_ndcg_e5c,
            },
            "delta_recall10": {
                "mean": d_r10_e5c,
                "ci_95_bca_lower": ci_l_r10_e5c,
                "ci_95_bca_upper": ci_h_r10_e5c,
            },
            "delta_mrr10": {
                "mean": d_mrr_e5c,
                "ci_95_bca_lower": ci_l_mrr_e5c,
                "ci_95_bca_upper": ci_h_mrr_e5c,
            },
            "mcnemar": mcnemar_e5c,
        },
        "vs_e6c_top20_generic": {
            "delta_ndcg10": {
                "mean": d_ndcg_e6c,
                "ci_95_bca_lower": ci_l_ndcg_e6c,
                "ci_95_bca_upper": ci_h_ndcg_e6c,
            },
            "delta_recall10": {
                "mean": d_r10_e6c,
                "ci_95_bca_lower": ci_l_r10_e6c,
                "ci_95_bca_upper": ci_h_r10_e6c,
            },
            "delta_mrr10": {
                "mean": d_mrr_e6c,
                "ci_95_bca_lower": ci_l_mrr_e6c,
                "ci_95_bca_upper": ci_h_mrr_e6c,
            },
            "mcnemar": mcnemar_e6c,
        },
    }

    metrics_payload = {
        "experiment_id": "E7C-DomainReranker-Top20-Provisional",
        "description": "Provisional evaluation of fine-tuned domain reranker on Benchmark v0 Development",
        "workflow_mode": "PROVISIONAL_AI_FILTERED_PENDING_HUMAN_REVIEW",
        "candidate_depth": candidate_depth,
        "metrics": overall_m,
        "latency": latency_telemetry,
        "domain_breakdown": domain_m,
        "typology_breakdown": typology_m,
        "statistical_tests": statistical_tests,
        "transition_summary": {
            "e7_vs_e5c_improved_ndcg": len(improved_vs_e5c),
            "e7_vs_e5c_degraded_ndcg": len(degraded_vs_e5c),
            "e7_vs_e5c_recovered_misses": len(recovered_misses_vs_e5c),
            "e7_vs_e5c_regressed_misses": len(regressed_misses_vs_e5c),
            "e7_vs_e5c_demoted_in_pool": len(demoted_in_pool_vs_e5c),
            "e7_vs_e6c_improved_ndcg": len(improved_vs_e6c),
            "e7_vs_e6c_degraded_ndcg": len(degraded_vs_e6c),
            "e7_vs_e6c_recovered_misses": len(recovered_misses_vs_e6c),
            "e7_vs_e6c_regressed_misses": len(regressed_misses_vs_e6c),
        },
    }

    with open(out_metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"Persisted metrics to {out_metrics_path.name}.")

    manifest_payload = {
        "experiment_id": "E7C-DomainReranker-Top20-Provisional",
        "model_dir": str(model_dir.relative_to(root)),
        "stage": "Stage-2 Cross-Encoder Reranker",
        "candidate_source": "E5C (BM25 + Matched-Easy Dense RRF k=60)",
        "candidate_depth": candidate_depth,
        "benchmark_file": str(benchmark_path.relative_to(root)),
        "benchmark_sha256": benchmark_sha,
        "corpus_chunks_sha256": corpus_sha,
        "overall_metrics": overall_m,
        "latency_telemetry": latency_telemetry,
        "statistical_tests": statistical_tests,
        "status": "COMPLETED_PROVISIONAL",
    }

    with open(out_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_payload, f, indent=2)
    print(f"Persisted manifest to {out_manifest_path.name}.")

    print("\n" + "=" * 80)
    print("RESULTS FOR E7C-DomainReranker-Top20-Provisional:")
    print("=" * 80)
    print(f"  NDCG@10:   {overall_m['ndcg_at_10']:.4f}")
    print(f"  Recall@10: {overall_m['recall_at_10']:.4f}")
    print(f"  MRR@10:    {overall_m['mrr_at_10']:.4f}")
    print(f"  HitRate@10:{overall_m['hit_rate_at_10']:.4f} | HitRate@20: {overall_m['hit_rate_at_20']:.4f}")
    print(f"  Top-10 Failures: {overall_m['top10_failures']} / {len(benchmark_queries)} ({overall_m['failure_rate']*100:.1f}%)")
    print(f"  Rerank Latency P50: {latency_telemetry['rerank_only_p50_ms']:.1f} ms | P95: {latency_telemetry['rerank_only_p95_ms']:.1f} ms")
    print(f"  Total Pipeline P50: {latency_telemetry['total_end_to_end_p50_ms']:.1f} ms | P95: {latency_telemetry['total_end_to_end_p95_ms']:.1f} ms")
    print("-" * 80)
    print("Comparison vs Stage-1 E5C:")
    print(f"  Delta NDCG@10:   {d_ndcg_e5c:+.4f} (95% BCa CI: [{ci_l_ndcg_e5c:+.4f}, {ci_h_ndcg_e5c:+.4f}])")
    print(f"  Delta Recall@10: {d_r10_e5c:+.4f} (95% BCa CI: [{ci_l_r10_e5c:+.4f}, {ci_h_r10_e5c:+.4f}])")
    print(f"  Delta MRR@10:    {d_mrr_e5c:+.4f} (95% BCa CI: [{ci_l_mrr_e5c:+.4f}, {ci_h_mrr_e5c:+.4f}])")
    print(f"  McNemar Test:    {mcnemar_e5c['reporting']}")
    print("-" * 80)
    print("Comparison vs Generic E6C-Top20:")
    print(f"  Delta NDCG@10:   {d_ndcg_e6c:+.4f} (95% BCa CI: [{ci_l_ndcg_e6c:+.4f}, {ci_h_ndcg_e6c:+.4f}])")
    print(f"  Delta Recall@10: {d_r10_e6c:+.4f} (95% BCa CI: [{ci_l_r10_e6c:+.4f}, {ci_h_r10_e6c:+.4f}])")
    print(f"  Delta MRR@10:    {d_mrr_e6c:+.4f} (95% BCa CI: [{ci_l_mrr_e6c:+.4f}, {ci_h_mrr_e6c:+.4f}])")
    print(f"  McNemar Test:    {mcnemar_e6c['reporting']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
