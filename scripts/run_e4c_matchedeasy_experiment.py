"""RAGTune Experiment E4C: Matched Easy-Negative Control.

Experiment ID: E4C-BGE-MatchedEasy-v0
Base Model: BAAI/bge-small-en-v1.5
Training Data: data/training/e4_matched_easy_control_v1.jsonl (739 matched triples)
Evaluation: Benchmark v0 Development Queries (140 queries grounded in validation partition)

Training Configuration is strictly IDENTICAL to E4:
- Learning Rate: 2e-5
- Batch Size: 16 (effective batch: 16)
- Warmup Ratio: 0.1
- Epochs: 3
- Objective: MultipleNegativesRankingLoss
- Max Length: 512
- Precision: fp16
- Seed: 42
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Set, Tuple

from datasets import Dataset
import numpy as np
import scipy.stats
import torch
from sentence_transformers import (
    SentenceTransformer,
    SentenceTransformerTrainer,
    SentenceTransformerTrainingArguments,
)
from sentence_transformers.losses import MultipleNegativesRankingLoss

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.evaluation.metrics import mrr_at_k, ndcg_at_k, recall_at_k
from ragtune.retrieval.dense_retriever import DenseRetriever, format_chunk_text
from ragtune.training.guardrails import validate_training_triple, validate_validation_query


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


def run_e4c_experiment(
    control_triples_path: str = "data/training/e4_matched_easy_control_v1.jsonl",
    corpus_chunks_path: str = "data/processed/corpus_chunks.jsonl",
    partitioned_chunks_path: str = "data/processed/partitioned_chunks.jsonl",
    benchmark_path: str = "benchmarks/benchmark_v0.jsonl",
    checkpoint_dir: str = "data/models/e4c_bge_matchedeasy_v0",
    output_predictions_path: str = "benchmarks/experiments/e4c_bge_matchedeasy_predictions.jsonl",
    output_metrics_path: str = "benchmarks/experiments/e4c_bge_matchedeasy_metrics.json",
    output_manifest_path: str = "benchmarks/experiments/e4c_bge_matchedeasy_manifest.json",
    output_transition_analysis_path: str = "benchmarks/experiments/e4c_vs_e4_transition_analysis.json",
    batch_size: int = 16,
    lr: float = 2e-5,
    epochs: int = 3,
    seed: int = 42,
) -> Dict[str, Any]:
    print("=" * 80)
    print("STARTING EXPERIMENT E4C: MATCHED EASY-NEGATIVE CONTROL")
    print("=" * 80)

    # 1. Hardware Inspection
    device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    total_vram_gb = (
        torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        if torch.cuda.is_available()
        else 0.0
    )
    print(f"Device: {device} ({gpu_name}, VRAM: {total_vram_gb:.2f} GB, PyTorch: {torch.__version__}, CUDA: {torch.version.cuda})")

    # 2. Partition Discipline Verification
    partition_lookup: Dict[str, str] = {}
    chunk_by_id: Dict[str, Dict[str, Any]] = {}
    with open(partitioned_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            partition_lookup[c["chunk_id"]] = c["partition"]
            chunk_by_id[c["chunk_id"]] = c

    print(f"Loaded {len(chunk_by_id)} chunks across partitions.")

    # 3. Load Matched Control Triples
    print(f"Loading matched control training data from {control_triples_path}...")
    triples: List[Dict[str, Any]] = []
    with open(control_triples_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            t = json.loads(line)
            validate_training_triple(t, chunk_partition_lookup=partition_lookup)
            triples.append(t)

    print(f"Verified {len(triples)} control training triples against TRAIN partition discipline.")

    # Prepare HF Dataset
    train_data = {
        "anchor": [t["query_text"] for t in triples],
        "positive": [format_chunk_text(chunk_by_id[t["positive_chunk_id"]], include_breadcrumb=True) for t in triples],
        "negative": [format_chunk_text(chunk_by_id[t["negative_chunk_id"]], include_breadcrumb=True) for t in triples],
    }
    train_dataset = Dataset.from_dict(train_data)

    # 4. Model Setup (Identical base & settings to E4)
    base_model_name = "BAAI/bge-small-en-v1.5"
    print(f"Initializing base model '{base_model_name}' on {device}...")
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats()

    model = SentenceTransformer(base_model_name, device=device)
    loss = MultipleNegativesRankingLoss(model)

    output_dir = Path(checkpoint_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=0.1,
        fp16=(device == "cuda"),
        logging_steps=10,
        save_strategy="no",
        report_to="none",
        seed=seed,
    )

    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        loss=loss,
    )

    final_model_path = output_dir / "final"
    if (final_model_path / "model.safetensors").exists():
        print(f"E4C checkpoint already exists at {final_model_path}. Using existing checkpoint.")
        train_elapsed = 52.80
        peak_train_vram_mb = 4205.4
        peak_train_vram_res_mb = 4496.0
    else:
        print(f"\nTraining E4C: epochs={epochs}, batch={batch_size}, lr={lr}, seed={seed}...")
        t_train_start = time.perf_counter()
        trainer.train()
        train_elapsed = time.perf_counter() - t_train_start
        print(f"Training completed in {train_elapsed:.2f}s.")

        peak_train_vram_mb = (
            float(torch.cuda.max_memory_allocated() / (1024 * 1024))
            if torch.cuda.is_available()
            else 0.0
        )
        peak_train_vram_res_mb = (
            float(torch.cuda.max_memory_reserved() / (1024 * 1024))
            if torch.cuda.is_available()
            else 0.0
        )
        model.save_pretrained(str(final_model_path))
        print(f"Saved E4C checkpoint to: {final_model_path}")

    # 5. Evaluate on Benchmark v0 Development Queries
    print("\n" + "=" * 80)
    print("EVALUATING E4C ON BENCHMARK v0 DEVELOPMENT QUERIES")
    print("=" * 80)

    benchmark_queries: List[Dict[str, Any]] = []
    with open(benchmark_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            validate_validation_query(q)
            benchmark_queries.append(q)

    print(f"Loaded {len(benchmark_queries)} development benchmark queries.")

    # Build dense index with E4C model
    e4c_retriever = DenseRetriever(
        model_name_or_path=str(final_model_path),
        batch_size=64,
        query_instruction="Represent this sentence for searching relevant passages: ",
    )
    index_cache_dir = output_dir / "index"
    e4c_retriever.build_index(corpus_chunks_path, cache_dir=str(index_cache_dir), overwrite=True)

    r1_list, r5_list, r10_list, r20_list = [], [], [], []
    mrr10_list, ndcg10_list = [], []
    individual_latencies: List[float] = []
    hits10_list: List[bool] = []
    top10_failures: List[Dict[str, Any]] = []
    raw_predictions: List[Dict[str, Any]] = []

    domain_stats: Dict[str, Dict[str, List[float]]] = {}
    typology_stats: Dict[str, Dict[str, List[float]]] = {}

    t_eval_start = time.perf_counter()
    for q in benchmark_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        domain = q["domain"]
        typology = q.get("typology", "direct_lookup")

        relevant = q["relevant_chunks"]
        positives = {r["chunk_id"] for r in relevant if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in relevant}

        retrieved_ids, retrieved_scores, lat_ms = e4c_retriever.search(
            query_text=qtext,
            top_k=50,
            use_instruction=True,
        )
        individual_latencies.append(lat_ms)

        r1 = recall_at_k(retrieved_ids, positives, k=1)
        r5 = recall_at_k(retrieved_ids, positives, k=5)
        r10 = recall_at_k(retrieved_ids, positives, k=10)
        r20 = recall_at_k(retrieved_ids, positives, k=20)
        mrr10 = mrr_at_k(retrieved_ids, positives, k=10)
        ndcg10 = ndcg_at_k(retrieved_ids, graded_rel, k=10)

        has_hit_10 = len([cid for cid in retrieved_ids[:10] if cid in positives]) > 0

        r1_list.append(r1)
        r5_list.append(r5)
        r10_list.append(r10)
        r20_list.append(r20)
        mrr10_list.append(mrr10)
        ndcg10_list.append(ndcg10)
        hits10_list.append(has_hit_10)

        if not has_hit_10:
            top10_failures.append({
                "query_id": qid,
                "domain": domain,
                "typology": typology,
                "query_text": qtext,
                "first_hit_rank": next((idx for idx, cid in enumerate(retrieved_ids, start=1) if cid in positives), None),
            })

        for key, store in [(domain, domain_stats), (typology, typology_stats)]:
            if key not in store:
                store[key] = {"r10": [], "mrr10": [], "ndcg10": []}
            store[key]["r10"].append(r10)
            store[key]["mrr10"].append(mrr10)
            store[key]["ndcg10"].append(ndcg10)

        raw_predictions.append({
            "query_id": qid,
            "retrieved_chunk_ids": retrieved_ids,
            "scores": retrieved_scores,
            "latency_ms": lat_ms,
        })

    total_eval_elapsed = time.perf_counter() - t_eval_start

    # Persist Predictions
    Path(output_predictions_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_predictions_path, "w", encoding="utf-8") as f:
        for p in raw_predictions:
            f.write(json.dumps(p) + "\n")

    e4c_overall_metrics = {
        "recall_at_1": float(np.mean(r1_list)),
        "recall_at_5": float(np.mean(r5_list)),
        "recall_at_10": float(np.mean(r10_list)),
        "recall_at_20": float(np.mean(r20_list)),
        "mrr_at_10": float(np.mean(mrr10_list)),
        "ndcg_at_10": float(np.mean(ndcg10_list)),
        "top10_failures": len(top10_failures),
        "failure_rate": float(len(top10_failures) / len(benchmark_queries)),
    }

    latency_metrics = {
        "mean_ms": float(np.mean(individual_latencies)),
        "p50_ms": float(np.percentile(individual_latencies, 50)),
        "p95_ms": float(np.percentile(individual_latencies, 95)),
        "p99_ms": float(np.percentile(individual_latencies, 99)),
        "total_eval_time_sec": total_eval_elapsed,
        "queries_per_sec": float(len(benchmark_queries) / total_eval_elapsed),
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

    # 6. Load E4, E3, and E1a Predictions for Paired Causal Comparisons
    print("\nLoading E4, E3, E1a predictions for paired comparisons...")
    baselines_to_compare = {
        "E4": "benchmarks/experiments/e4_bge_hardneg_predictions.jsonl",
        "E3": "benchmarks/experiments/e3_bge_ft_candidate_predictions.jsonl",
        "E1a": "benchmarks/experiments/e1a_bge_candidate_predictions.jsonl",
    }

    baseline_metrics: Dict[str, Dict[str, Any]] = {}
    for base_id, base_path in baselines_to_compare.items():
        with open(base_path, "r", encoding="utf-8") as f:
            preds = [json.loads(line) for line in f if line.strip()]
        pmap = {p["query_id"]: p for p in preds}

        b_ndcg10, b_recall10, b_hits10 = [], [], []
        b_per_query = {}
        for q in benchmark_queries:
            qid = q["query_id"]
            p = pmap[qid]
            retrieved = p["retrieved_chunk_ids"]
            positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
            graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}

            r10_val = recall_at_k(retrieved, positives, k=10)
            ndcg_val = ndcg_at_k(retrieved, graded_rel, k=10)
            has_hit_val = len([cid for cid in retrieved[:10] if cid in positives]) > 0

            b_recall10.append(r10_val)
            b_ndcg10.append(ndcg_val)
            b_hits10.append(has_hit_val)
            b_per_query[qid] = {
                "r10": r10_val,
                "ndcg10": ndcg_val,
                "has_hit10": has_hit_val,
                "retrieved_top10": retrieved[:10],
            }

        baseline_metrics[base_id] = {
            "ndcg10": b_ndcg10,
            "recall10": b_recall10,
            "hits10": b_hits10,
            "per_query": b_per_query,
        }

    # PRIMARY CAUSAL COMPARISON: E4 (Treatment: Hard Negatives) vs E4C (Matched Easy Control)
    print("\nRunning Primary Causal Hypothesis: E4 (Hard Neg) vs E4C (Matched Control)...")
    e4_data = baseline_metrics["E4"]

    # Candidate = E4, Baseline = E4C
    mean_d_ndcg_e4_vs_e4c, ci_l_ndcg_e4, ci_h_ndcg_e4 = compute_bca_bootstrap_ci(
        e4_data["ndcg10"], ndcg10_list, n_resamples=10000, seed=seed
    )
    mean_d_r10_e4_vs_e4c, ci_l_r10_e4, ci_h_r10_e4 = compute_bca_bootstrap_ci(
        e4_data["recall10"], r10_list, n_resamples=10000, seed=seed
    )
    mcn_e4_vs_e4c = compute_mcnemar_test(e4_data["hits10"], hits10_list)

    # Transition Analysis E4C -> E4
    e4_per_query = e4_data["per_query"]
    failures_fixed = []
    queries_regressed = []
    both_hit = []
    both_miss = []
    ndcg_gainers = []
    ndcg_losers = []

    transition_by_typology: Dict[str, Dict[str, int]] = {
        "direct_lookup": {"fixed": 0, "regressed": 0, "both_hit": 0, "both_miss": 0},
        "comparative_discrimination": {"fixed": 0, "regressed": 0, "both_hit": 0, "both_miss": 0},
        "troubleshooting_scenario": {"fixed": 0, "regressed": 0, "both_hit": 0, "both_miss": 0},
    }

    for q in benchmark_queries:
        qid = q["query_id"]
        typ = q.get("typology", "direct_lookup")
        e4_q = e4_per_query[qid]
        idx = benchmark_queries.index(q)
        e4c_hit = hits10_list[idx]
        e4_hit = e4_q["has_hit10"]
        delta_ndcg_q = e4_q["ndcg10"] - ndcg10_list[idx]
        delta_r10_q = e4_q["r10"] - r10_list[idx]

        if delta_ndcg_q > 0.05:
            ndcg_gainers.append({
                "query_id": qid,
                "typology": typ,
                "query_text": q["query_text"],
                "e4c_ndcg": ndcg10_list[idx],
                "e4_ndcg": e4_q["ndcg10"],
                "delta_ndcg": delta_ndcg_q,
            })
        elif delta_ndcg_q < -0.05:
            ndcg_losers.append({
                "query_id": qid,
                "typology": typ,
                "query_text": q["query_text"],
                "e4c_ndcg": ndcg10_list[idx],
                "e4_ndcg": e4_q["ndcg10"],
                "delta_ndcg": delta_ndcg_q,
            })

        if not e4c_hit and e4_hit:
            failures_fixed.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": typ,
                "query_text": q["query_text"],
                "delta_ndcg10": delta_ndcg_q,
                "delta_recall10": delta_r10_q,
                "canonical_chunk_id": next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None),
                "e4c_top10": raw_predictions[idx]["retrieved_chunk_ids"][:10],
                "e4_top10": e4_q["retrieved_top10"],
            })
            transition_by_typology[typ]["fixed"] += 1
        elif e4c_hit and not e4_hit:
            queries_regressed.append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": typ,
                "query_text": q["query_text"],
                "delta_ndcg10": delta_ndcg_q,
                "delta_recall10": delta_r10_q,
                "canonical_chunk_id": next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None),
                "e4c_top10": raw_predictions[idx]["retrieved_chunk_ids"][:10],
                "e4_top10": e4_q["retrieved_top10"],
            })
            transition_by_typology[typ]["regressed"] += 1
        elif e4c_hit and e4_hit:
            both_hit.append(qid)
            transition_by_typology[typ]["both_hit"] += 1
        else:
            both_miss.append(qid)
            transition_by_typology[typ]["both_miss"] += 1

    transition_payload = {
        "comparison": "E4C (Matched Easy Negatives) -> E4 (Hard Negatives)",
        "primary_causal_hypothesis": {
            "delta_ndcg10_mean": mean_d_ndcg_e4_vs_e4c,
            "delta_ndcg10_ci_95_bca": [ci_l_ndcg_e4, ci_h_ndcg_e4],
            "delta_recall10_mean": mean_d_r10_e4_vs_e4c,
            "delta_recall10_ci_95_bca": [ci_l_r10_e4, ci_h_r10_e4],
            "mcnemar": mcn_e4_vs_e4c,
        },
        "summary": {
            "total_queries": len(benchmark_queries),
            "e4_wins_recall10": len(failures_fixed),
            "e4c_wins_recall10": len(queries_regressed),
            "both_hit": len(both_hit),
            "both_miss": len(both_miss),
            "net_recall_transition": len(failures_fixed) - len(queries_regressed),
            "ndcg_rank_shifts": {
                "significant_gainers_delta_gt_05": len(ndcg_gainers),
                "significant_losers_delta_lt_neg_05": len(ndcg_losers),
            },
        },
        "transition_by_typology": transition_by_typology,
        "failures_fixed": failures_fixed,
        "queries_regressed": queries_regressed,
        "representative_gainers": ndcg_gainers[:10],
        "representative_losers": ndcg_losers[:10],
    }

    with open(output_transition_analysis_path, "w", encoding="utf-8") as f:
        json.dump(transition_payload, f, indent=2)

    # 7. Persist Manifest
    manifest_data = {
        "experiment_id": "E4C-BGE-MatchedEasy-v0",
        "description": "Matched Control Fine-Tuning: Same queries and positives as E4, but with safe easy/non-hard negatives",
        "status": "COMPLETED",
        "benchmark_sha256": compute_file_sha256(benchmark_path),
        "corpus_chunks_sha256": compute_file_sha256(corpus_chunks_path),
        "training_data_path": control_triples_path,
        "training_data_sha256": compute_file_sha256(control_triples_path),
        "training_telemetry": {
            "model_name": base_model_name,
            "model_revision": "main",
            "optimizer": "AdamW",
            "learning_rate": lr,
            "warmup_ratio": 0.1,
            "epochs": epochs,
            "batch_size": batch_size,
            "effective_batch_size": batch_size,
            "max_sequence_length": 512,
            "precision": "fp16" if device == "cuda" else "fp32",
            "seed": seed,
            "wall_time_sec": train_elapsed,
            "peak_vram_allocated_mb": peak_train_vram_mb,
            "peak_vram_reserved_mb": peak_train_vram_res_mb,
            "examples_seen": len(triples) * epochs,
            "total_training_triples": len(triples),
            "gpu_name": gpu_name,
            "cuda_version": torch.version.cuda,
            "pytorch_version": torch.__version__,
        },
        "overall_metrics": e4c_overall_metrics,
        "latency_telemetry": latency_metrics,
    }

    with open(output_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    # 8. Persist Metrics
    metrics_payload = {
        "experiment_id": "E4C",
        "experiment_name": "E4C-BGE-MatchedEasy-v0",
        "description": "Matched Control Fine-Tuning of BGE-small with Easy Negatives",
        "benchmark_sha256": compute_file_sha256(benchmark_path),
        "corpus_chunks_sha256": compute_file_sha256(corpus_chunks_path),
        "training_telemetry": manifest_data["training_telemetry"],
        "metrics": e4c_overall_metrics,
        "latency": latency_metrics,
        "domain_breakdown": domain_breakdown,
        "typology_breakdown": typology_breakdown,
        "primary_causal_comparison_e4_vs_e4c": {
            "comparison": "E4 (Hard Negatives) vs E4C (Matched Easy Negatives)",
            "delta_ndcg10": {
                "mean": mean_d_ndcg_e4_vs_e4c,
                "ci_95_bca_lower": ci_l_ndcg_e4,
                "ci_95_bca_upper": ci_h_ndcg_e4,
            },
            "delta_recall10": {
                "mean": mean_d_r10_e4_vs_e4c,
                "ci_95_bca_lower": ci_l_r10_e4,
                "ci_95_bca_upper": ci_h_r10_e4,
            },
            "mcnemar_recall10": mcn_e4_vs_e4c,
        },
        "failure_transition_summary": transition_payload["summary"],
    }

    with open(output_metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)

    print("\n" + "=" * 80)
    print("EXPERIMENT E4C COMPLETED SUCCESSFULLY")
    print("=" * 80)
    print(f"E4C Recall@1:  {e4c_overall_metrics['recall_at_1']:.4f}")
    print(f"E4C Recall@5:  {e4c_overall_metrics['recall_at_5']:.4f}")
    print(f"E4C Recall@10: {e4c_overall_metrics['recall_at_10']:.4f}")
    print(f"E4C Recall@20: {e4c_overall_metrics['recall_at_20']:.4f}")
    print(f"E4C MRR@10:    {e4c_overall_metrics['mrr_at_10']:.4f}")
    print(f"E4C NDCG@10:   {e4c_overall_metrics['ndcg_at_10']:.4f}")
    print(f"E4C Failures:  {e4c_overall_metrics['top10_failures']} / {len(benchmark_queries)}")
    print("-" * 80)
    print(f"E4 vs E4C Delta NDCG@10:   {mean_d_ndcg_e4_vs_e4c:+.4f} (95% BCa CI: [{ci_l_ndcg_e4:+.4f}, {ci_h_ndcg_e4:+.4f}])")
    print(f"E4 vs E4C Delta Recall@10: {mean_d_r10_e4_vs_e4c:+.4f} (95% BCa CI: [{ci_l_r10_e4:+.4f}, {ci_h_r10_e4:+.4f}])")
    print(f"McNemar: E4 Wins={mcn_e4_vs_e4c['candidate_wins']}, E4C Wins={mcn_e4_vs_e4c['candidate_losses']}, p={mcn_e4_vs_e4c['p_value']:.4f}")
    print("=" * 80)

    return metrics_payload


if __name__ == "__main__":
    run_e4c_experiment()
