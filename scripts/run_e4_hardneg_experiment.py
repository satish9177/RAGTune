"""RAGTune Core Retrieval-Learning Experiment: E4-BGE-HardNeg-v0.

Trains BGE-small with verified hard negatives mined from the TRAIN partition
(with multi-layered false-negative protection) and evaluates on canonical
Benchmark v0 development queries.

Comparison Chain:
- E1a: BGE-small zero-shot
- E3: BGE-small TRAIN-only basic contrastive fine-tune (in-batch negatives only)
- E4: BGE-small TRAIN-only fine-tune with verified hard negatives
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

# Add project root to sys.path
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
    cand_scores: List[float],
    base_scores: List[float],
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
    hits_cand: List[bool],
    hits_base: List[bool],
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


def run_e4_experiment(
    train_triples_path: str = "data/training/hard_negatives_v1.jsonl",
    corpus_chunks_path: str = "data/processed/corpus_chunks.jsonl",
    partitioned_chunks_path: str = "data/processed/partitioned_chunks.jsonl",
    benchmark_path: str = "benchmarks/benchmark_v0.jsonl",
    checkpoint_dir: str = "data/models/e4_bge_hardneg_v0",
    output_predictions_path: str = "benchmarks/experiments/e4_bge_hardneg_predictions.jsonl",
    output_metrics_path: str = "benchmarks/experiments/e4_bge_hardneg_metrics.json",
    output_transition_analysis_path: str = "benchmarks/experiments/e4_failure_transition_analysis.json",
    output_report_path: str = "benchmarks/experiments/E4_EVALUATION_REPORT.md",
    lr: float = 2e-5,
    epochs: int = 3,
    batch_size: int = 16,
    seed: int = 42,
) -> Dict[str, Any]:
    print("=" * 80)
    print("RAGTUNE EXPERIMENT E4: BGE-small with Verified Hard Negatives (TRAIN Only)")
    print("=" * 80)

    # 1. Validate Partition Discipline & Training Triples
    print(f"Loading partition manifest and verifying {train_triples_path}...")
    partition_lookup: Dict[str, str] = {}
    with open(partitioned_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                partition_lookup[item["chunk_id"]] = item["partition"]

    train_triples: List[Dict[str, Any]] = []
    with open(train_triples_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                t = json.loads(line)
                validate_training_triple(t, chunk_partition_lookup=partition_lookup)
                train_triples.append(t)

    print(f"Verified {len(train_triples)} training triples (100% TRAIN partition compliant).")

    # 2. Build Dataset
    print(f"Loading corpus texts from {corpus_chunks_path}...")
    corpus_lookup: Dict[str, str] = {}
    corpus_chunks_by_id: Dict[str, Dict[str, Any]] = {}
    with open(corpus_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                cid = c["chunk_id"]
                corpus_lookup[cid] = format_chunk_text(c, include_breadcrumb=True)
                corpus_chunks_by_id[cid] = c

    anchors = []
    positives = []
    negatives = []

    for t in train_triples:
        anchors.append(t["query_text"])
        positives.append(corpus_lookup[t["positive_chunk_id"]])
        negatives.append(corpus_lookup[t["negative_chunk_id"]])

    train_dataset = Dataset.from_dict({
        "anchor": anchors,
        "positive": positives,
        "negative": negatives,
    })
    print(f"Constructed training dataset: {len(train_dataset)} triples.")

    # 3. Model & Loss Setup (Identical base & comparable settings to E3)
    device = "cuda" if torch.cuda.is_available() else "cpu"
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

    print(f"\nTraining E4: epochs={epochs}, batch={batch_size}, lr={lr}, seed={seed}...")
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

    # Save fine-tuned checkpoint
    final_model_path = output_dir / "final"
    model.save_pretrained(str(final_model_path))
    print(f"Saved E4 checkpoint to: {final_model_path}")

    # 4. Evaluate Fine-Tuned Model on Benchmark v0
    print("\n" + "=" * 80)
    print("EVALUATING E4 (E4-BGE-HardNeg-v0) ON BENCHMARK v0 DEVELOPMENT QUERIES")
    print("=" * 80)

    with open(benchmark_path, "r", encoding="utf-8") as f:
        benchmark_queries = [json.loads(line) for line in f if line.strip()]

    for q in benchmark_queries:
        validate_validation_query(q)

    print(f"Loaded {len(benchmark_queries)} development queries (all validated).")

    # Build dense index with E4 model
    e4_retriever = DenseRetriever(
        model_name_or_path=str(final_model_path),
        batch_size=64,
        query_instruction="Represent this sentence for searching relevant passages: ",
    )
    index_cache_dir = output_dir / "index"
    e4_retriever.build_index(corpus_chunks_path, cache_dir=str(index_cache_dir), overwrite=True)

    individual_latencies: List[float] = []
    predictions: List[Dict[str, Any]] = []

    t_eval_start = time.perf_counter()
    for q in benchmark_queries:
        retrieved_ids, scores, lat_ms = e4_retriever.search(
            query_text=q["query_text"],
            top_k=50,
            use_instruction=True,
        )
        individual_latencies.append(lat_ms)
        predictions.append({
            "query_id": q["query_id"],
            "retrieved_chunk_ids": retrieved_ids,
            "scores": scores,
            "latency_ms": lat_ms,
        })
    total_eval_elapsed = time.perf_counter() - t_eval_start

    # Persist predictions
    Path(output_predictions_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_predictions_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p) + "\n")
    print(f"Persisted E4 predictions to: {output_predictions_path}")

    # 5. Compute E4 Metrics
    r1_list, r5_list, r10_list, r20_list = [], [], [], []
    mrr10_list, ndcg10_list = [], []
    hits10_list = []

    domain_stats: Dict[str, Dict[str, List[float]]] = {}
    typology_stats: Dict[str, Dict[str, List[float]]] = {}
    per_query_e4: Dict[str, Dict[str, Any]] = {}

    for q, p in zip(benchmark_queries, predictions):
        qid = q["query_id"]
        domain = q["domain"]
        typology = q["typology"]
        retrieved = p["retrieved_chunk_ids"]
        positives = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}

        r1 = recall_at_k(retrieved, positives, k=1)
        r5 = recall_at_k(retrieved, positives, k=5)
        r10 = recall_at_k(retrieved, positives, k=10)
        r20 = recall_at_k(retrieved, positives, k=20)
        mrr = mrr_at_k(retrieved, positives, k=10)
        ndcg = ndcg_at_k(retrieved, graded_rel, k=10)

        hits_10 = [cid for cid in retrieved[:10] if cid in positives]
        has_hit = len(hits_10) > 0

        r1_list.append(r1)
        r5_list.append(r5)
        r10_list.append(r10)
        r20_list.append(r20)
        mrr10_list.append(mrr)
        ndcg10_list.append(ndcg)
        hits10_list.append(has_hit)

        per_query_e4[qid] = {
            "query_text": q["query_text"],
            "domain": domain,
            "typology": typology,
            "r1": r1,
            "r5": r5,
            "r10": r10,
            "r20": r20,
            "mrr10": mrr,
            "ndcg10": ndcg,
            "has_hit10": has_hit,
            "retrieved_top10": retrieved[:10],
            "canonical_chunk_id": next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None),
            "positives": list(positives),
        }

        # Domain breakdown
        if domain not in domain_stats:
            domain_stats[domain] = {"r10": [], "mrr10": [], "ndcg10": []}
        domain_stats[domain]["r10"].append(r10)
        domain_stats[domain]["mrr10"].append(mrr)
        domain_stats[domain]["ndcg10"].append(ndcg)

        # Typology breakdown
        if typology not in typology_stats:
            typology_stats[typology] = {"r10": [], "mrr10": [], "ndcg10": []}
        typology_stats[typology]["r10"].append(r10)
        typology_stats[typology]["mrr10"].append(mrr)
        typology_stats[typology]["ndcg10"].append(ndcg)

    e4_overall_metrics = {
        "recall_at_1": float(np.mean(r1_list)),
        "recall_at_5": float(np.mean(r5_list)),
        "recall_at_10": float(np.mean(r10_list)),
        "recall_at_20": float(np.mean(r20_list)),
        "mrr_at_10": float(np.mean(mrr10_list)),
        "ndcg_at_10": float(np.mean(ndcg10_list)),
        "top10_failures": int(sum(1 for h in hits10_list if not h)),
        "failure_rate": float(sum(1 for h in hits10_list if not h) / len(benchmark_queries)),
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

    # 6. Load Baseline Predictions and Run Paired Comparisons
    print("\nLoading baseline predictions for paired statistical evaluation...")
    baselines_to_compare = {
        "E3": "benchmarks/experiments/e3_bge_ft_candidate_predictions.jsonl",
        "E1a": "benchmarks/experiments/e1a_bge_candidate_predictions.jsonl",
        "E0": "benchmarks/experiments/e0_v0_candidate_predictions.jsonl",
        "E2a": "benchmarks/experiments/e2a_rrf_bge_candidate_predictions.jsonl",
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

            r10 = recall_at_k(retrieved, positives, k=10)
            ndcg = ndcg_at_k(retrieved, graded_rel, k=10)
            has_hit = len([cid for cid in retrieved[:10] if cid in positives]) > 0

            b_recall10.append(r10)
            b_ndcg10.append(ndcg)
            b_hits10.append(has_hit)
            b_per_query[qid] = {
                "r10": r10,
                "ndcg10": ndcg,
                "has_hit10": has_hit,
                "retrieved_top10": retrieved[:10],
            }

        baseline_metrics[base_id] = {
            "ndcg10": b_ndcg10,
            "recall10": b_recall10,
            "hits10": b_hits10,
            "per_query": b_per_query,
        }

    # Statistical tests: E4 vs E3 (Primary learning hypothesis!), E4 vs E1a, E4 vs E0, E4 vs E2a
    statistical_tests = []
    comparisons_meta = [
        ("E4", "E3", "Primary Learning Hypothesis: Hard-Negative FT vs Basic Contrastive FT", "Pre-specified Primary Retrieval-Learning Hypothesis"),
        ("E4", "E1a", "Hard-Negative FT vs Zero-Shot BGE Baseline", "Pre-specified Secondary Adaptation Hypothesis"),
        ("E4", "E0", "Hard-Negative FT vs Lexical BM25 Baseline", "Pre-specified Secondary Comparison"),
        ("E4", "E2a", "Hard-Negative FT vs Hybrid Stage 1 (BM25+BGE)", "Exploratory Comparison"),
    ]

    for cand_id, base_id, desc, pre_spec in comparisons_meta:
        b_data = baseline_metrics[base_id]
        mean_d_ndcg, ci_l_ndcg, ci_h_ndcg = compute_bca_bootstrap_ci(
            ndcg10_list, b_data["ndcg10"], n_resamples=10000, seed=seed
        )
        mean_d_r10, ci_l_r10, ci_h_r10 = compute_bca_bootstrap_ci(
            r10_list, b_data["recall10"], n_resamples=10000, seed=seed
        )
        mcnemar = compute_mcnemar_test(hits10_list, b_data["hits10"])

        statistical_tests.append({
            "comparison": f"{cand_id} vs {base_id}",
            "description": desc,
            "pre_specified_status": pre_spec,
            "candidate_id": cand_id,
            "baseline_id": base_id,
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
            "mcnemar_recall10": mcnemar,
        })

    # 7. Detailed Failure-Transition Analysis (E3 -> E4)
    print("\nExecuting comprehensive E3 -> E4 Failure-Transition Analysis...")
    e3_per_query = baseline_metrics["E3"]["per_query"]

    failures_fixed = []
    queries_regressed = []
    both_hit = []
    both_miss = []

    # Typology and query-type tracking
    transition_by_typology: Dict[str, Dict[str, int]] = {
        "direct_lookup": {"fixed": 0, "regressed": 0, "maintained": 0, "unresolved": 0},
        "comparative_discrimination": {"fixed": 0, "regressed": 0, "maintained": 0, "unresolved": 0},
        "troubleshooting_scenario": {"fixed": 0, "regressed": 0, "maintained": 0, "unresolved": 0},
    }

    for q in benchmark_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        domain = q["domain"]
        typology = q["typology"]
        e4_info = per_query_e4[qid]
        e3_info = e3_per_query[qid]

        e4_hit = e4_info["has_hit10"]
        e3_hit = e3_info["has_hit10"]

        if e4_hit and not e3_hit:
            failures_fixed.append({
                "query_id": qid,
                "query_text": qtext,
                "domain": domain,
                "typology": typology,
                "e3_top10": e3_info["retrieved_top10"],
                "e4_top10": e4_info["retrieved_top10"],
                "canonical_chunk_id": e4_info["canonical_chunk_id"],
                "delta_ndcg10": e4_info["ndcg10"] - e3_info["ndcg10"],
                "delta_recall10": e4_info["r10"] - e3_info["r10"],
            })
            transition_by_typology[typology]["fixed"] += 1
        elif not e4_hit and e3_hit:
            queries_regressed.append({
                "query_id": qid,
                "query_text": qtext,
                "domain": domain,
                "typology": typology,
                "e3_top10": e3_info["retrieved_top10"],
                "e4_top10": e4_info["retrieved_top10"],
                "canonical_chunk_id": e4_info["canonical_chunk_id"],
                "delta_ndcg10": e4_info["ndcg10"] - e3_info["ndcg10"],
                "delta_recall10": e4_info["r10"] - e3_info["r10"],
            })
            transition_by_typology[typology]["regressed"] += 1
        elif e4_hit and e3_hit:
            both_hit.append(qid)
            transition_by_typology[typology]["maintained"] += 1
        else:
            both_miss.append(qid)
            transition_by_typology[typology]["unresolved"] += 1

    # Analysis of semantically close distractors corrected
    distractor_corrections = []
    for fix in failures_fixed:
        # Check what was in E3 top-3 that got pushed down in E4
        e3_top3 = fix["e3_top10"][:3]
        e4_top10 = fix["e4_top10"]
        pushed_down = [cid for cid in e3_top3 if cid not in e4_top10[:3]]
        distractor_corrections.append({
            "query_id": fix["query_id"],
            "query_text": fix["query_text"],
            "distractors_pushed_down": pushed_down,
            "canonical_chunk_id": fix["canonical_chunk_id"],
        })

    failure_transition_analysis = {
        "comparison": "E3 (Basic FT) -> E4 (Hard-Negative FT)",
        "summary": {
            "total_queries": len(benchmark_queries),
            "failures_fixed_by_hard_negatives": len(failures_fixed),
            "previously_correct_queries_regressed": len(queries_regressed),
            "net_recall_transition": len(failures_fixed) - len(queries_regressed),
            "maintained_correct": len(both_hit),
            "persistent_failures": len(both_miss),
        },
        "transition_by_typology": transition_by_typology,
        "failures_fixed": failures_fixed,
        "queries_regressed": queries_regressed,
        "distractor_corrections": distractor_corrections,
    }

    # Persist Failure-Transition Analysis
    Path(output_transition_analysis_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_transition_analysis_path, "w", encoding="utf-8") as f:
        json.dump(failure_transition_analysis, f, indent=2)
    print(f"Persisted failure-transition analysis to: {output_transition_analysis_path}")

    # 8. Full Metrics Payload
    training_telemetry = {
        "model_name": base_model_name,
        "model_revision": "main",
        "training_data_path": train_triples_path,
        "training_data_sha256": compute_file_sha256(train_triples_path),
        "training_data_partition": "train",
        "optimizer": "AdamW",
        "learning_rate": lr,
        "num_train_epochs": epochs,
        "per_device_train_batch_size": batch_size,
        "gradient_accumulation_steps": 1,
        "effective_batch_size": batch_size,
        "warmup_ratio": 0.1,
        "objective_loss": "MultipleNegativesRankingLoss",
        "max_sequence_length": 512,
        "precision": "fp16" if device == "cuda" else "fp32",
        "peak_vram_allocated_mb": peak_train_vram_mb,
        "peak_vram_reserved_mb": peak_train_vram_res_mb,
        "wall_time_sec": train_elapsed,
        "examples_seen": len(train_dataset) * epochs,
        "total_training_triples": len(train_dataset),
        "seed": seed,
    }

    full_experiment_results = {
        "experiment_id": "E4",
        "experiment_name": "E4-BGE-HardNeg-v0",
        "description": "TRAIN-only Fine-Tuning of BGE-small with Verified Hard Negatives and Multi-Layer False-Negative Protection",
        "status": "COMPLETED",
        "benchmark_file": benchmark_path,
        "benchmark_sha256": compute_file_sha256(benchmark_path),
        "evaluation_scope": "Benchmark v0 Development Queries (validation partition only)",
        "training_telemetry": training_telemetry,
        "metrics": e4_overall_metrics,
        "latency": latency_metrics,
        "domain_breakdown": domain_breakdown,
        "typology_breakdown": typology_breakdown,
        "statistical_comparisons": statistical_tests,
        "failure_transition_summary": failure_transition_analysis["summary"],
    }

    Path(output_metrics_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_metrics_path, "w", encoding="utf-8") as f:
        json.dump(full_experiment_results, f, indent=2)
    print(f"Persisted E4 metrics to: {output_metrics_path}")

    # 9. Generate Markdown Evaluation Report
    report_md = f"""# RAGTune Experiment E4 Report: Hard-Negative Fine-Tuning

> **Model**: `E4-BGE-HardNeg-v0` (`BAAI/bge-small-en-v1.5` with verified hard negatives)  
> **Benchmark**: Benchmark v0 Development Benchmark (140 queries grounded in `validation`, SHA: `{full_experiment_results['benchmark_sha256']}`)  
> **Training Partition**: 100% `train` partition (0% validation, 0% frozen_test)  
> **Training Data**: `{train_triples_path}` ({len(train_dataset)} verified triples)  

---

## 1. Primary Model Comparison Matrix

| ID | Model / Configuration | Stage | Recall@1 | Recall@5 | Recall@10 | Recall@20 | MRR@10 | NDCG@10 | Top-10 Failures | P50 Latency | Peak VRAM |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | SQLite FTS5 BM25 | 1 (Lexical) | 0.3024 | 0.6333 | 0.7571 | 0.8536 | 0.6524 | 0.6184 | 11 (7.9%) | 23.7 ms | 0.0 MB |
| **E1a** | BGE-small Zero-Shot | 1 (Dense) | 0.3024 | 0.6548 | 0.7393 | 0.8321 | 0.6462 | 0.5986 | 14 (10.0%) | 16.4 ms | 379.7 MB |
| **E3** | BGE-small Basic FT (In-Batch Negs) | 1 (Fine-Tuned) | 0.3429 | 0.7012 | 0.7893 | 0.8500 | 0.6937 | 0.6350 | 9 (6.4%) | 17.3 ms | 379.7 MB |
| **E4** | **BGE-small Hard-Negative FT** | **1 (Hard-Neg FT)** | **{e4_overall_metrics['recall_at_1']:.4f}** | **{e4_overall_metrics['recall_at_5']:.4f}** | **{e4_overall_metrics['recall_at_10']:.4f}** | **{e4_overall_metrics['recall_at_20']:.4f}** | **{e4_overall_metrics['mrr_at_10']:.4f}** | **{e4_overall_metrics['ndcg_at_10']:.4f}** | **{e4_overall_metrics['top10_failures']} ({e4_overall_metrics['failure_rate']*100:.1f}%)** | **{latency_metrics['p50_ms']:.1f} ms** | **{peak_train_vram_mb:.1f} MB** |

---

## 2. Statistical Comparisons & Learning Hypothesis Testing

### Primary Learning Hypothesis: E4 (Hard Negatives) vs E3 (Basic Fine-Tuning)
- **Δ NDCG@10**: `{statistical_tests[0]['delta_ndcg10']['mean']:+.4f}` (95% BCa CI: `[{statistical_tests[0]['delta_ndcg10']['ci_95_bca_lower']:+.4f}, {statistical_tests[0]['delta_ndcg10']['ci_95_bca_upper']:+.4f}]`)
- **Δ Recall@10**: `{statistical_tests[0]['delta_recall10']['mean']:+.4f}` (95% BCa CI: `[{statistical_tests[0]['delta_recall10']['ci_95_bca_lower']:+.4f}, {statistical_tests[0]['delta_recall10']['ci_95_bca_upper']:+.4f}]`)
- **McNemar Discordant Counts (Recall@10)**: E4 Wins={statistical_tests[0]['mcnemar_recall10']['candidate_wins']}, E3 Wins={statistical_tests[0]['mcnemar_recall10']['candidate_losses']} (Tied Hits={statistical_tests[0]['mcnemar_recall10']['both_hit']}, Tied Misses={statistical_tests[0]['mcnemar_recall10']['both_miss']})
- **Significance**: $\\chi^2={statistical_tests[0]['mcnemar_recall10']['chi2_stat']:.3f}$, {statistical_tests[0]['mcnemar_recall10']['reporting']}

### E4 vs E1a (Hard Negatives vs Zero-Shot BGE)
- **Δ NDCG@10**: `{statistical_tests[1]['delta_ndcg10']['mean']:+.4f}` (95% BCa CI: `[{statistical_tests[1]['delta_ndcg10']['ci_95_bca_lower']:+.4f}, {statistical_tests[1]['delta_ndcg10']['ci_95_bca_upper']:+.4f}]`)
- **Δ Recall@10**: `{statistical_tests[1]['delta_recall10']['mean']:+.4f}` (95% BCa CI: `[{statistical_tests[1]['delta_recall10']['ci_95_bca_lower']:+.4f}, {statistical_tests[1]['delta_recall10']['ci_95_bca_upper']:+.4f}]`)
- **McNemar Discordant Counts (Recall@10)**: E4 Wins={statistical_tests[1]['mcnemar_recall10']['candidate_wins']}, E1a Wins={statistical_tests[1]['mcnemar_recall10']['candidate_losses']}
- **Significance**: $\\chi^2={statistical_tests[1]['mcnemar_recall10']['chi2_stat']:.3f}$, {statistical_tests[1]['mcnemar_recall10']['reporting']}

---

## 3. Failure-Transition Analysis (E3 → E4)

- **Failures Fixed by Hard Negatives**: {len(failures_fixed)} queries
- **Previously Correct Queries Regressed**: {len(queries_regressed)} queries
- **Net Recall Transition**: {len(failures_fixed) - len(queries_regressed):+d} queries
- **Maintained Top-10 Hits**: {len(both_hit)} queries
- **Persistent Top-10 Failures**: {len(both_miss)} queries

### Transition by Typology:
| Typology | Fixed | Regressed | Maintained | Unresolved |
|---|:---:|:---:|:---:|:---:|
| Direct Lookup | {transition_by_typology['direct_lookup']['fixed']} | {transition_by_typology['direct_lookup']['regressed']} | {transition_by_typology['direct_lookup']['maintained']} | {transition_by_typology['direct_lookup']['unresolved']} |
| Comparative Discrimination | {transition_by_typology['comparative_discrimination']['fixed']} | {transition_by_typology['comparative_discrimination']['regressed']} | {transition_by_typology['comparative_discrimination']['maintained']} | {transition_by_typology['comparative_discrimination']['unresolved']} |
| Troubleshooting Scenario | {transition_by_typology['troubleshooting_scenario']['fixed']} | {transition_by_typology['troubleshooting_scenario']['regressed']} | {transition_by_typology['troubleshooting_scenario']['maintained']} | {transition_by_typology['troubleshooting_scenario']['unresolved']} |

---

## 4. Training Telemetry
- **Base Model**: `{training_telemetry['model_name']}` (revision: `{training_telemetry['model_revision']}`)
- **Optimizer**: `{training_telemetry['optimizer']}` | **LR**: `{training_telemetry['learning_rate']}` | **Epochs**: `{training_telemetry['num_train_epochs']}`
- **Batch Size**: `{training_telemetry['per_device_train_batch_size']}` (effective: `{training_telemetry['effective_batch_size']}`)
- **Objective**: `{training_telemetry['objective_loss']}`
- **Sequence Length**: `{training_telemetry['max_sequence_length']}` | **Precision**: `{training_telemetry['precision']}`
- **Peak VRAM Allocated**: `{training_telemetry['peak_vram_allocated_mb']:.1f} MB` | **Reserved**: `{training_telemetry['peak_vram_reserved_mb']:.1f} MB`
- **Training Wall Time**: `{training_telemetry['wall_time_sec']:.2f} s` | **Examples Seen**: `{training_telemetry['examples_seen']}` | **Seed**: `{training_telemetry['seed']}`
"""

    Path(output_report_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_report_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Persisted E4 evaluation report to: {output_report_path}")

    print("\n" + "=" * 80)
    print("E4 EVALUATION COMPLETE")
    print(f"Recall@10: {e4_overall_metrics['recall_at_10']:.4f} (E3: 0.7893, E1a: 0.7393, E0: 0.7571)")
    print(f"NDCG@10:   {e4_overall_metrics['ndcg_at_10']:.4f} (E3: 0.6350, E1a: 0.5986, E0: 0.6184)")
    print(f"MRR@10:    {e4_overall_metrics['mrr_at_10']:.4f} (E3: 0.6937, E1a: 0.6462, E0: 0.6524)")
    print(f"Failures:  {e4_overall_metrics['top10_failures']} / 140 (E3: 9, E1a: 14, E0: 11)")
    print("=" * 80)

    return full_experiment_results


if __name__ == "__main__":
    run_e4_experiment()
