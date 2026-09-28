"""RAGTune Experiment E6: Generic Cross-Encoder Reranking Profiling.

Evaluates un-fine-tuned BAAI/bge-reranker-base on Stage-1 candidate sets:
- E6C-Reranker-E5C-Top20 (Primary Candidate Depth: 20)
- E6C-Reranker-E5C-Top50 (Primary Candidate Depth: 50)
- E6H-Reranker-E5H-Top50 (Secondary Controlled Comparison)

Evaluated exclusively on Benchmark v0 Development (140 queries).
Profiles latency, VRAM, quality trade-offs, and failure transitions.
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
import torch
from sentence_transformers import CrossEncoder

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


def run_reranking_experiment(
    exp_id: str,
    exp_name: str,
    stage1_name: str,
    stage1_preds_path: str,
    candidate_depth: int,
    reranker_model: CrossEncoder,
    chunk_by_id: Dict[str, Dict[str, Any]],
    benchmark_queries: List[Dict[str, Any]],
    output_preds_path: str,
    output_metrics_path: str,
    output_manifest_path: str,
    benchmark_sha: str,
    corpus_sha: str,
) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print(f"RUNNING RERANKING: {exp_name} (Candidate Depth: {candidate_depth})")
    print("=" * 80)

    with open(stage1_preds_path, "r", encoding="utf-8") as f:
        stage1_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}

    predictions: List[Dict[str, Any]] = []
    reranker_latencies: List[float] = []
    total_latencies: List[float] = []

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t_start_all = time.perf_counter()
    for q in benchmark_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        s1 = stage1_preds[qid]
        s1_ids = s1["retrieved_chunk_ids"]
        s1_lat = s1.get("latency_ms", 35.0)

        # Slice candidate depth
        cands_to_rerank = s1_ids[:candidate_depth]
        tail_cands = s1_ids[candidate_depth:]

        # Build pairs
        pairs = []
        for cid in cands_to_rerank:
            chunk = chunk_by_id[cid]
            c_text = format_chunk_text(chunk, include_breadcrumb=True)
            pairs.append((qtext, c_text))

        t0 = time.perf_counter()
        scores = reranker_model.predict(pairs, batch_size=candidate_depth, show_progress_bar=False, convert_to_numpy=True)
        rerank_ms = (time.perf_counter() - t0) * 1000.0

        reranker_latencies.append(rerank_ms)
        tot_ms = s1_lat + rerank_ms
        total_latencies.append(tot_ms)

        # Rank candidates descending by score
        scored_cands = sorted(zip(cands_to_rerank, [float(s) for s in scores]), key=lambda x: x[1], reverse=True)
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
    Path(output_preds_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_preds_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")

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

    manifest = {
        "experiment_id": exp_id,
        "experiment_name": exp_name,
        "stage": f"3 (Stage-2 Cross-Encoder Reranker, Candidate Depth {candidate_depth})",
        "status": "COMPLETED",
        "model_name": "BAAI/bge-reranker-base",
        "model_revision": "main",
        "stage1_source": stage1_name,
        "stage1_preds_path": stage1_preds_path,
        "candidate_depth": candidate_depth,
        "benchmark_sha256": benchmark_sha,
        "corpus_chunks_sha256": corpus_sha,
        "overall_metrics": overall_m,
        "latency_telemetry": latency_telemetry,
    }
    with open(output_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    metric_payload = {
        "experiment_id": exp_id,
        "metrics": overall_m,
        "latency": latency_telemetry,
        "domain_breakdown": domain_m,
        "typology_breakdown": typology_m,
    }
    with open(output_metrics_path, "w", encoding="utf-8") as f:
        json.dump(metric_payload, f, indent=2)

    print(f"Results for {exp_id}:")
    print(f"  Recall@1:  {overall_m['recall_at_1']:.4f} | Recall@10: {overall_m['recall_at_10']:.4f} | Recall@20: {overall_m['recall_at_20']:.4f}")
    print(f"  HitRate@1: {overall_m['hit_rate_at_1']:.4f} | HitRate@10:{overall_m['hit_rate_at_10']:.4f} | HitRate@20:{overall_m['hit_rate_at_20']:.4f}")
    print(f"  MRR@10:    {overall_m['mrr_at_10']:.4f} | NDCG@10:   {overall_m['ndcg_at_10']:.4f} | Top-10 Failures: {overall_m['top10_failures']}")
    print(f"  Rerank Latency P50: {latency_telemetry['rerank_only_p50_ms']:.1f} ms | Total End-to-End P50: {latency_telemetry['total_end_to_end_p50_ms']:.1f} ms")

    return {
        "manifest": manifest,
        "metrics": metric_payload,
        "per_query": per_query_m,
        "predictions": predictions,
    }


def main():
    print("=" * 80)
    print("STARTING E6 RERANKER PROFILING EXPERIMENTS")
    print("=" * 80)

    benchmark_path = "benchmarks/benchmark_v0.jsonl"
    corpus_chunks_path = "data/processed/corpus_chunks.jsonl"
    e5c_preds_path = "benchmarks/experiments/e5c_hybrid_matchedeasy_predictions.jsonl"
    e5h_preds_path = "benchmarks/experiments/e5h_hybrid_hardneg_predictions.jsonl"

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

    # 2. Load corpus chunks for passage formatting
    print("Loading corpus chunks lookup...")
    chunk_by_id: Dict[str, Dict[str, Any]] = {}
    with open(corpus_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            chunk_by_id[c["chunk_id"]] = c

    # 3. Initialize Cross-Encoder
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading BAAI/bge-reranker-base on {device}...")
    reranker_model = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512)

    # 4. Run E6C-Top20
    res_e6c_top20 = run_reranking_experiment(
        exp_id="E6C-Reranker-E5C-Top20",
        exp_name="E6C-Reranker-E5C-Top20",
        stage1_name="E5C (BM25 + Matched-Easy Dense RRF)",
        stage1_preds_path=e5c_preds_path,
        candidate_depth=20,
        reranker_model=reranker_model,
        chunk_by_id=chunk_by_id,
        benchmark_queries=benchmark_queries,
        output_preds_path="benchmarks/experiments/e6c_top20_predictions.jsonl",
        output_metrics_path="benchmarks/experiments/e6c_top20_metrics.json",
        output_manifest_path="benchmarks/experiments/e6c_top20_manifest.json",
        benchmark_sha=benchmark_sha,
        corpus_sha=corpus_sha,
    )

    # 5. Run E6C-Top50
    res_e6c_top50 = run_reranking_experiment(
        exp_id="E6C-Reranker-E5C-Top50",
        exp_name="E6C-Reranker-E5C-Top50",
        stage1_name="E5C (BM25 + Matched-Easy Dense RRF)",
        stage1_preds_path=e5c_preds_path,
        candidate_depth=50,
        reranker_model=reranker_model,
        chunk_by_id=chunk_by_id,
        benchmark_queries=benchmark_queries,
        output_preds_path="benchmarks/experiments/e6c_top50_predictions.jsonl",
        output_metrics_path="benchmarks/experiments/e6c_top50_metrics.json",
        output_manifest_path="benchmarks/experiments/e6c_top50_manifest.json",
        benchmark_sha=benchmark_sha,
        corpus_sha=corpus_sha,
    )

    # 6. Run E6H-Top50 (Secondary controlled comparison)
    res_e6h_top50 = run_reranking_experiment(
        exp_id="E6H-Reranker-E5H-Top50",
        exp_name="E6H-Reranker-E5H-Top50",
        stage1_name="E5H (BM25 + Hard-Negative Dense RRF)",
        stage1_preds_path=e5h_preds_path,
        candidate_depth=50,
        reranker_model=reranker_model,
        chunk_by_id=chunk_by_id,
        benchmark_queries=benchmark_queries,
        output_preds_path="benchmarks/experiments/e6h_top50_predictions.jsonl",
        output_metrics_path="benchmarks/experiments/e6h_top50_metrics.json",
        output_manifest_path="benchmarks/experiments/e6h_top50_manifest.json",
        benchmark_sha=benchmark_sha,
        corpus_sha=corpus_sha,
    )

    # 7. Step E: Failure Transition Analysis for E6C-Top50 vs E5C Stage-1
    print("\n" + "=" * 80)
    print("STEP E: RERANKER FAILURE TRANSITION ANALYSIS (E5C Stage-1 -> E6C-Top50)")
    print("=" * 80)

    with open(e5c_preds_path, "r", encoding="utf-8") as f:
        e5c_preds = {json.loads(line)["query_id"]: json.loads(line) for line in f if line.strip()}
    e6c_preds = {p["query_id"]: p for p in res_e6c_top50["predictions"]}

    rank_improvements = []
    rank_regressions = []
    demoted_in_pool = []
    stage1_unrecoverable_misses = []
    vocab_code_failures = []

    for q in benchmark_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}
        canonical_cid = next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None)

        s1_ret = e5c_preds[qid]["retrieved_chunk_ids"]
        e6_ret = e6c_preds[qid]["retrieved_chunk_ids"]

        s1_ndcg = ndcg_at_k(s1_ret, graded_rel, k=10)
        e6_ndcg = ndcg_at_k(e6_ret, graded_rel, k=10)
        delta_ndcg = e6_ndcg - s1_ndcg

        s1_best_rank = next((idx for idx, cid in enumerate(s1_ret, start=1) if cid in positives), None)
        e6_best_rank = next((idx for idx, cid in enumerate(e6_ret, start=1) if cid in positives), None)

        # 1. Rank improvements & regressions
        if delta_ndcg > 0.05:
            rank_improvements.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "s1_rank": s1_best_rank,
                "e6_rank": e6_best_rank,
                "s1_ndcg": s1_ndcg,
                "e6_ndcg": e6_ndcg,
                "delta_ndcg": delta_ndcg,
            })
        elif delta_ndcg < -0.05:
            rank_regressions.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "s1_rank": s1_best_rank,
                "e6_rank": e6_best_rank,
                "s1_ndcg": s1_ndcg,
                "e6_ndcg": e6_ndcg,
                "delta_ndcg": delta_ndcg,
            })

        # 2. Candidate present in Stage-1 pool (<= 50) but reranker demoted it outside top-10
        if s1_best_rank is not None and s1_best_rank <= 50:
            if e6_best_rank is not None and e6_best_rank > 10:
                demoted_in_pool.append({
                    "query_id": qid,
                    "domain": q["domain"],
                    "typology": q["typology"],
                    "query_text": qtext,
                    "s1_rank": s1_best_rank,
                    "e6_rank": e6_best_rank,
                    "canonical_chunk_id": canonical_cid,
                })

        # 3. Stage-1 miss that reranker could never recover (absent from top-50 pool)
        if s1_best_rank is None or s1_best_rank > 50:
            stage1_unrecoverable_misses.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "s1_rank": s1_best_rank,
                "canonical_chunk_id": canonical_cid,
            })

        # 4. Exact identifier/code or vocabulary mismatch failure
        if (delta_ndcg < -0.05) and ("_" in qtext or "(" in qtext or "." in qtext):
            vocab_code_failures.append({
                "query_id": qid,
                "query_text": qtext,
                "domain": q["domain"],
                "delta_ndcg": delta_ndcg,
            })

    transition_analysis = {
        "comparison": "E5C (BM25 + Matched-Easy Dense Stage-1) -> E6C-Top50 (Cross-Encoder Reranker)",
        "summary": {
            "total_queries": len(benchmark_queries),
            "rank_improvements_delta_gt_05": len(rank_improvements),
            "rank_regressions_delta_lt_neg_05": len(rank_regressions),
            "relevant_candidate_in_pool_but_demoted_outside_top10": len(demoted_in_pool),
            "stage1_unrecoverable_misses_outside_depth50": len(stage1_unrecoverable_misses),
            "exact_identifier_code_failures": len(vocab_code_failures),
        },
        "rank_improvements": rank_improvements,
        "rank_regressions": rank_regressions,
        "demoted_in_pool": demoted_in_pool,
        "stage1_unrecoverable_misses": stage1_unrecoverable_misses,
        "vocab_code_failures": vocab_code_failures,
    }

    out_trans_path = "benchmarks/experiments/e6c_failure_transition_analysis.json"
    with open(out_trans_path, "w", encoding="utf-8") as f:
        json.dump(transition_analysis, f, indent=2)

    print(f"Persisted failure transition analysis to: {out_trans_path}")
    print(f"Rank improvements: {len(rank_improvements)}")
    print(f"Rank regressions:  {len(rank_regressions)}")
    print(f"Demoted outside top-10 by reranker: {len(demoted_in_pool)}")
    print(f"Unrecoverable misses (absent from top-50 pool): {len(stage1_unrecoverable_misses)}")


if __name__ == "__main__":
    main()
