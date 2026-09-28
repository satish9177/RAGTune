"""RAGTune Experiments E5C and E5H: Production-Style Lexical + Dense Hybrid Fusion.

Experiments:
- E5C = BM25 + E4C Dense (Matched Easy Negative Control), RRF k=60
- E5H = BM25 + E4 Dense (Hard-Negative Treatment), RRF k=60

Evaluation Scope: Canonical Benchmark v0 Development (140 queries in validation partition)
No new training. Pinned RRF k=60. Evaluated against predeclared practical floors:
- Delta Recall@10 >= +0.025
- Delta NDCG@10 >= +0.020
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import scipy.stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.evaluation.metrics import mrr_at_k, ndcg_at_k, recall_at_k
from ragtune.retrieval.hybrid_retriever import reciprocal_rank_fusion
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
            "reporting": "McNemar p=1.0000 (unadjusted for multiple comparisons)",
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
        "reporting": f"McNemar p={p_val:.4f} (unadjusted for multiple comparisons)",
    }


def evaluate_ranking(
    benchmark_queries: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    pred_map = {p["query_id"]: p for p in predictions}

    r1_list, r5_list, r10_list, r20_list = [], [], [], []
    mrr10_list, ndcg10_list = [], []
    hits10_list: List[bool] = []
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
        mrr10 = mrr_at_k(retrieved_ids, positives, k=10)
        ndcg10 = ndcg_at_k(retrieved_ids, graded_rel, k=10)
        has_hit = len([cid for cid in retrieved_ids[:10] if cid in positives]) > 0

        r1_list.append(r1)
        r5_list.append(r5)
        r10_list.append(r10)
        r20_list.append(r20)
        mrr10_list.append(mrr10)
        ndcg10_list.append(ndcg10)
        hits10_list.append(has_hit)

        if not has_hit:
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
                store[key] = {"r10": [], "mrr10": [], "ndcg10": []}
            store[key]["r10"].append(r10)
            store[key]["mrr10"].append(mrr10)
            store[key]["ndcg10"].append(ndcg10)

        per_query_results.append({
            "query_id": qid,
            "r10": r10,
            "ndcg10": ndcg10,
            "mrr10": mrr10,
            "has_hit10": has_hit,
            "retrieved_top10": retrieved_ids[:10],
        })

    overall_metrics = {
        "recall_at_1": float(np.mean(r1_list)),
        "recall_at_5": float(np.mean(r5_list)),
        "recall_at_10": float(np.mean(r10_list)),
        "recall_at_20": float(np.mean(r20_list)),
        "mrr_at_10": float(np.mean(mrr10_list)),
        "ndcg_at_10": float(np.mean(ndcg10_list)),
        "top10_failures": len(top10_failures),
        "failure_rate": float(len(top10_failures) / len(benchmark_queries)),
    }

    domain_breakdown = {
        d: {
            "recall_at_10": float(np.mean(vals["r10"])),
            "mrr_at_10": float(np.mean(vals["mrr10"])),
            "ndcg_at_10": float(np.mean(vals["ndcg10"])),
            "query_count": len(vals["r10"]),
        }
        for d, vals in sorted(domain_stats.items())
    }

    typology_breakdown = {
        t: {
            "recall_at_10": float(np.mean(vals["r10"])),
            "mrr_at_10": float(np.mean(vals["mrr10"])),
            "ndcg_at_10": float(np.mean(vals["ndcg10"])),
            "query_count": len(vals["r10"]),
        }
        for t, vals in sorted(typology_stats.items())
    }

    return overall_metrics, domain_breakdown, typology_breakdown, per_query_results


def main():
    print("=" * 80)
    print("RUNNING EXPERIMENT E5: PRODUCTION-STYLE HYBRID FUSION (E5C vs E5H)")
    print("=" * 80)

    benchmark_path = "benchmarks/benchmark_v0.jsonl"
    corpus_chunks_path = "data/processed/corpus_chunks.jsonl"
    e0_preds_path = "benchmarks/experiments/e0_v0_candidate_predictions.jsonl"
    e4c_preds_path = "benchmarks/experiments/e4c_bge_matchedeasy_predictions.jsonl"
    e4_preds_path = "benchmarks/experiments/e4_bge_hardneg_predictions.jsonl"

    e5c_preds_path = "benchmarks/experiments/e5c_hybrid_matchedeasy_predictions.jsonl"
    e5c_metrics_path = "benchmarks/experiments/e5c_hybrid_matchedeasy_metrics.json"
    e5c_manifest_path = "benchmarks/experiments/e5c_hybrid_matchedeasy_manifest.json"

    e5h_preds_path = "benchmarks/experiments/e5h_hybrid_hardneg_predictions.jsonl"
    e5h_metrics_path = "benchmarks/experiments/e5h_hybrid_hardneg_metrics.json"
    e5h_manifest_path = "benchmarks/experiments/e5h_hybrid_hardneg_manifest.json"

    transition_path = "benchmarks/experiments/e5h_vs_e5c_transition_analysis.json"

    # 1. Load benchmark queries
    benchmark_queries: List[Dict[str, Any]] = []
    with open(benchmark_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            validate_validation_query(q)
            benchmark_queries.append(q)

    print(f"Loaded {len(benchmark_queries)} validated Benchmark v0 development queries.")

    # 2. Load precomputed predictions
    with open(e0_preds_path, "r", encoding="utf-8") as f:
        e0_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}
    with open(e4c_preds_path, "r", encoding="utf-8") as f:
        e4c_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}
    with open(e4_preds_path, "r", encoding="utf-8") as f:
        e4_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}

    print(f"Loaded predictions: BM25={len(e0_preds)}, E4C={len(e4c_preds)}, E4={len(e4_preds)}")

    # 3. Fuse E5C (BM25 + E4C) and E5H (BM25 + E4) via RRF (k=60)
    print("\nComputing RRF (k=60) fusion for E5C and E5H...")
    e5c_predictions: List[Dict[str, Any]] = []
    e5h_predictions: List[Dict[str, Any]] = []

    e5c_latencies: List[float] = []
    e5h_latencies: List[float] = []

    for q in benchmark_queries:
        qid = q["query_id"]
        bm25_res = e0_preds[qid]
        e4c_res = e4c_preds[qid]
        e4_res = e4_preds[qid]

        bm25_ids = bm25_res["retrieved_chunk_ids"]
        e4c_ids = e4c_res["retrieved_chunk_ids"]
        e4_ids = e4_res["retrieved_chunk_ids"]

        # E5C Fusion
        t0 = time.perf_counter()
        fused_c_ids, fused_c_scores = reciprocal_rank_fusion([bm25_ids, e4c_ids], rrf_k=60, top_k=50)
        fusion_lat_c = (time.perf_counter() - t0) * 1000.0
        tot_lat_c = bm25_res.get("latency_ms", 12.0) + e4c_res.get("latency_ms", 17.0) + fusion_lat_c
        e5c_latencies.append(tot_lat_c)

        e5c_predictions.append({
            "query_id": qid,
            "retrieved_chunk_ids": fused_c_ids,
            "scores": fused_c_scores,
            "latency_ms": tot_lat_c,
        })

        # E5H Fusion
        t0 = time.perf_counter()
        fused_h_ids, fused_h_scores = reciprocal_rank_fusion([bm25_ids, e4_ids], rrf_k=60, top_k=50)
        fusion_lat_h = (time.perf_counter() - t0) * 1000.0
        tot_lat_h = bm25_res.get("latency_ms", 12.0) + e4_res.get("latency_ms", 17.0) + fusion_lat_h
        e5h_latencies.append(tot_lat_h)

        e5h_predictions.append({
            "query_id": qid,
            "retrieved_chunk_ids": fused_h_ids,
            "scores": fused_h_scores,
            "latency_ms": tot_lat_h,
        })

    # Persist fused predictions
    Path(e5c_preds_path).parent.mkdir(parents=True, exist_ok=True)
    with open(e5c_preds_path, "w", encoding="utf-8") as f:
        for p in e5c_predictions:
            f.write(json.dumps(p) + "\n")

    with open(e5h_preds_path, "w", encoding="utf-8") as f:
        for p in e5h_predictions:
            f.write(json.dumps(p) + "\n")

    print(f"Persisted E5C predictions to: {e5c_preds_path}")
    print(f"Persisted E5H predictions to: {e5h_preds_path}")

    # 4. Evaluate Metrics
    e5c_metrics, e5c_domain, e5c_typology, e5c_per_query = evaluate_ranking(benchmark_queries, e5c_predictions)
    e5h_metrics, e5h_domain, e5h_typology, e5h_per_query = evaluate_ranking(benchmark_queries, e5h_predictions)

    e5c_latency_meta = {
        "mean_ms": float(np.mean(e5c_latencies)),
        "p50_ms": float(np.percentile(e5c_latencies, 50)),
        "p95_ms": float(np.percentile(e5c_latencies, 95)),
        "p99_ms": float(np.percentile(e5c_latencies, 99)),
    }
    e5h_latency_meta = {
        "mean_ms": float(np.mean(e5h_latencies)),
        "p50_ms": float(np.percentile(e5h_latencies, 50)),
        "p95_ms": float(np.percentile(e5h_latencies, 95)),
        "p99_ms": float(np.percentile(e5h_latencies, 99)),
    }

    # 5. Paired Statistical Analysis: E5H vs E5C (10,000 BCa Bootstrap)
    print("\nRunning Paired 10,000 BCa Bootstrap for E5H vs E5C...")
    e5c_ndcg = [q["ndcg10"] for q in e5c_per_query]
    e5c_r10 = [q["r10"] for q in e5c_per_query]
    e5c_hits = [q["has_hit10"] for q in e5c_per_query]

    e5h_ndcg = [q["ndcg10"] for q in e5h_per_query]
    e5h_r10 = [q["r10"] for q in e5h_per_query]
    e5h_hits = [q["has_hit10"] for q in e5h_per_query]

    mean_d_ndcg, ci_l_ndcg, ci_h_ndcg = compute_bca_bootstrap_ci(e5h_ndcg, e5c_ndcg, n_resamples=10000, seed=42)
    mean_d_r10, ci_l_r10, ci_h_r10 = compute_bca_bootstrap_ci(e5h_r10, e5c_r10, n_resamples=10000, seed=42)
    mcn_test = compute_mcnemar_test(e5h_hits, e5c_hits)

    # 6. Detailed Transition & Mechanism Analysis
    failures_fixed_by_e5h = []
    queries_regressed_by_e5h = []
    both_hit = []
    both_miss = []
    ndcg_gainers = []
    ndcg_losers = []

    transition_by_typology: Dict[str, Dict[str, int]] = {
        "direct_lookup": {"fixed": 0, "regressed": 0, "both_hit": 0, "both_miss": 0},
        "comparative_discrimination": {"fixed": 0, "regressed": 0, "both_hit": 0, "both_miss": 0},
        "troubleshooting_scenario": {"fixed": 0, "regressed": 0, "both_hit": 0, "both_miss": 0},
    }

    for idx, q in enumerate(benchmark_queries):
        qid = q["query_id"]
        typ = q.get("typology", "direct_lookup")
        c_hit = e5c_hits[idx]
        h_hit = e5h_hits[idx]
        delta_ndcg_q = e5h_ndcg[idx] - e5c_ndcg[idx]
        delta_r10_q = e5h_r10[idx] - e5c_r10[idx]

        if delta_ndcg_q > 0.05:
            ndcg_gainers.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": typ,
                "query_text": q["query_text"],
                "e5c_ndcg": e5c_ndcg[idx],
                "e5h_ndcg": e5h_ndcg[idx],
                "delta_ndcg": delta_ndcg_q,
            })
        elif delta_ndcg_q < -0.05:
            ndcg_losers.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": typ,
                "query_text": q["query_text"],
                "e5c_ndcg": e5c_ndcg[idx],
                "e5h_ndcg": e5h_ndcg[idx],
                "delta_ndcg": delta_ndcg_q,
            })

        if not c_hit and h_hit:
            failures_fixed_by_e5h.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": typ,
                "query_text": q["query_text"],
                "delta_ndcg10": delta_ndcg_q,
                "delta_recall10": delta_r10_q,
                "canonical_chunk_id": next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None),
                "e5c_top10": e5c_predictions[idx]["retrieved_chunk_ids"][:10],
                "e5h_top10": e5h_predictions[idx]["retrieved_chunk_ids"][:10],
            })
            transition_by_typology[typ]["fixed"] += 1
        elif c_hit and not h_hit:
            queries_regressed_by_e5h.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": typ,
                "query_text": q["query_text"],
                "delta_ndcg10": delta_ndcg_q,
                "delta_recall10": delta_r10_q,
                "canonical_chunk_id": next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None),
                "e5c_top10": e5c_predictions[idx]["retrieved_chunk_ids"][:10],
                "e5h_top10": e5h_predictions[idx]["retrieved_chunk_ids"][:10],
            })
            transition_by_typology[typ]["regressed"] += 1
        elif c_hit and h_hit:
            both_hit.append(qid)
            transition_by_typology[typ]["both_hit"] += 1
        else:
            both_miss.append(qid)
            transition_by_typology[typ]["both_miss"] += 1

    transition_payload = {
        "comparison": "E5C (BM25 + Matched Easy Dense) -> E5H (BM25 + Hard-Negative Dense)",
        "fusion_method": "Reciprocal Rank Fusion (RRF)",
        "rrf_k": 60,
        "primary_causal_hypothesis": {
            "delta_ndcg10_mean": mean_d_ndcg,
            "delta_ndcg10_ci_95_bca": [ci_l_ndcg, ci_h_ndcg],
            "delta_recall10_mean": mean_d_r10,
            "delta_recall10_ci_95_bca": [ci_l_r10, ci_h_r10],
            "mcnemar": mcn_test,
            "predeclared_practical_floors": {
                "delta_recall10_floor": 0.025,
                "delta_recall10_passed": mean_d_r10 >= 0.025,
                "delta_ndcg10_floor": 0.020,
                "delta_ndcg10_passed": mean_d_ndcg >= 0.020,
            },
        },
        "summary": {
            "total_queries": len(benchmark_queries),
            "e5h_wins_recall10": len(failures_fixed_by_e5h),
            "e5c_wins_recall10": len(queries_regressed_by_e5h),
            "both_hit": len(both_hit),
            "both_miss": len(both_miss),
            "net_recall_transition": len(failures_fixed_by_e5h) - len(queries_regressed_by_e5h),
            "ndcg_rank_shifts": {
                "significant_gainers_delta_gt_05": len(ndcg_gainers),
                "significant_losers_delta_lt_neg_05": len(ndcg_losers),
            },
        },
        "transition_by_typology": transition_by_typology,
        "failures_fixed_by_e5h": failures_fixed_by_e5h,
        "queries_regressed_by_e5h": queries_regressed_by_e5h,
        "representative_gainers": ndcg_gainers[:10],
        "representative_losers": ndcg_losers[:10],
    }

    with open(transition_path, "w", encoding="utf-8") as f:
        json.dump(transition_payload, f, indent=2)

    # 7. Persist Manifests and Metrics for E5C and E5H
    bm25_sha = compute_file_sha256(e0_preds_path)
    benchmark_sha = compute_file_sha256(benchmark_path)
    corpus_sha = compute_file_sha256(corpus_chunks_path)

    e5c_manifest = {
        "experiment_id": "E5C",
        "experiment_name": "E5C-Hybrid-BM25-E4C-v0",
        "stage": "2 (Production Hybrid: BM25 + Matched Easy Control Dense)",
        "status": "COMPLETED",
        "description": "Production-style hybrid fusion combining SQLite FTS5 BM25 and E4C Matched Easy Control dense retriever using fixed RRF (k=60)",
        "fusion_configuration": {
            "method": "Reciprocal Rank Fusion (RRF)",
            "rrf_k": 60,
            "lexical_retriever": "SQLite FTS5 BM25 (E0)",
            "dense_retriever": "E4C-BGE-MatchedEasy-v0",
            "candidate_depth_per_retriever": 50,
            "top_k_fused": 50,
        },
        "benchmark_sha256": benchmark_sha,
        "corpus_chunks_sha256": corpus_sha,
        "overall_metrics": e5c_metrics,
        "latency_telemetry": e5c_latency_meta,
    }
    with open(e5c_manifest_path, "w", encoding="utf-8") as f:
        json.dump(e5c_manifest, f, indent=2)

    e5c_metric_payload = {
        "experiment_id": "E5C",
        "metrics": e5c_metrics,
        "latency": e5c_latency_meta,
        "domain_breakdown": e5c_domain,
        "typology_breakdown": e5c_typology,
    }
    with open(e5c_metrics_path, "w", encoding="utf-8") as f:
        json.dump(e5c_metric_payload, f, indent=2)

    e5h_manifest = {
        "experiment_id": "E5H",
        "experiment_name": "E5H-Hybrid-BM25-E4-v0",
        "stage": "2 (Production Hybrid: BM25 + Hard-Negative Dense)",
        "status": "COMPLETED",
        "description": "Production-style hybrid fusion combining SQLite FTS5 BM25 and E4 Hard-Negative fine-tuned dense retriever using fixed RRF (k=60)",
        "fusion_configuration": {
            "method": "Reciprocal Rank Fusion (RRF)",
            "rrf_k": 60,
            "lexical_retriever": "SQLite FTS5 BM25 (E0)",
            "dense_retriever": "E4-BGE-HardNeg-v0",
            "candidate_depth_per_retriever": 50,
            "top_k_fused": 50,
        },
        "benchmark_sha256": benchmark_sha,
        "corpus_chunks_sha256": corpus_sha,
        "overall_metrics": e5h_metrics,
        "latency_telemetry": e5h_latency_meta,
    }
    with open(e5h_manifest_path, "w", encoding="utf-8") as f:
        json.dump(e5h_manifest, f, indent=2)

    e5h_metric_payload = {
        "experiment_id": "E5H",
        "metrics": e5h_metrics,
        "latency": e5h_latency_meta,
        "domain_breakdown": e5h_domain,
        "typology_breakdown": e5h_typology,
        "paired_comparison_e5h_vs_e5c": {
            "delta_ndcg10": {
                "mean": mean_d_ndcg,
                "ci_95_bca_lower": ci_l_ndcg,
                "ci_95_bca_upper": ci_h_ndcg,
            },
            "delta_recall10": {
                "mean": mean_d_r10,
                "ci_95_bca_lower": ci_l_r10,
                "ci_95_bca_upper": ci_h_r10,
            },
            "mcnemar_recall10": mcn_test,
        },
        "failure_transition_summary": transition_payload["summary"],
    }
    with open(e5h_metrics_path, "w", encoding="utf-8") as f:
        json.dump(e5h_metric_payload, f, indent=2)

    # Print summary tables
    print("\n" + "=" * 80)
    print("EXPERIMENTS E5C AND E5H COMPLETED SUCCESSFULLY")
    print("=" * 80)
    print(f"E5C Recall@1:  {e5c_metrics['recall_at_1']:.4f} | E5H: {e5h_metrics['recall_at_1']:.4f}")
    print(f"E5C Recall@5:  {e5c_metrics['recall_at_5']:.4f} | E5H: {e5h_metrics['recall_at_5']:.4f}")
    print(f"E5C Recall@10: {e5c_metrics['recall_at_10']:.4f} | E5H: {e5h_metrics['recall_at_10']:.4f}")
    print(f"E5C Recall@20: {e5c_metrics['recall_at_20']:.4f} | E5H: {e5h_metrics['recall_at_20']:.4f}")
    print(f"E5C MRR@10:    {e5c_metrics['mrr_at_10']:.4f} | E5H: {e5h_metrics['mrr_at_10']:.4f}")
    print(f"E5C NDCG@10:   {e5c_metrics['ndcg_at_10']:.4f} | E5H: {e5h_metrics['ndcg_at_10']:.4f}")
    print(f"E5C Failures:  {e5c_metrics['top10_failures']} / 140   | E5H: {e5h_metrics['top10_failures']} / 140")
    print("-" * 80)
    print(f"Delta NDCG@10 (E5H - E5C):   {mean_d_ndcg:+.4f} (95% BCa CI: [{ci_l_ndcg:+.4f}, {ci_h_ndcg:+.4f}])")
    print(f"Delta Recall@10 (E5H - E5C): {mean_d_r10:+.4f} (95% BCa CI: [{ci_l_r10:+.4f}, {ci_h_r10:+.4f}])")
    print(f"McNemar: E5H Wins={mcn_test['candidate_wins']}, E5C Wins={mcn_test['candidate_losses']}, p={mcn_test['p_value']:.4f}")
    print(f"Floor Check: Delta Recall ({mean_d_r10:+.4f} >= +0.025) -> {mean_d_r10 >= 0.025}")
    print(f"Floor Check: Delta NDCG   ({mean_d_ndcg:+.4f} >= +0.020) -> {mean_d_ndcg >= 0.020}")
    print("=" * 80)


if __name__ == "__main__":
    main()
