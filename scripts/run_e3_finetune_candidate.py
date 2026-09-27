"""Run Provisional E3 Contrastive Dense Fine-Tuning (E3-BGE-FT-v0-candidate).

Model: BAAI/bge-small-en-v1.5
Training: In-batch negatives contrastive fine-tuning (MultipleNegativesRankingLoss)
Dataset: data/training/retriever_train_v0.jsonl (100% TRAIN partition)
Evaluates retrieval over the frozen corpus (11,645 chunks) on 140 candidate development queries.
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

from datasets import Dataset
import numpy as np
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


def run_e3_finetune(
    train_triples_path: str = "data/training/retriever_train_v0.jsonl",
    corpus_chunks_path: str = "data/processed/corpus_chunks.jsonl",
    partitioned_path: str = "data/processed/partitioned_chunks.jsonl",
    benchmark_path: str = "benchmarks/benchmark_v0.jsonl",
    checkpoint_dir: str = "data/checkpoints/bge_small_ft_e3",
    manifest_path: str = "benchmarks/experiments/e3_bge_ft_candidate_manifest.json",
    predictions_path: str = "benchmarks/experiments/e3_bge_ft_candidate_predictions.jsonl",
    failures_path: str = "benchmarks/experiments/e3_bge_ft_candidate_failures.jsonl",
    metrics_path: str = "benchmarks/experiments/e3_bge_ft_candidate_metrics.json",
    epochs: int = 3,
    batch_size: int = 16,
    lr: float = 2e-5,
) -> Dict[str, Any]:
    print("=" * 75)
    print("RAGTUNE EXPERIMENT E3-BGE-FT-v0-candidate: CONTRASTIVE FINE-TUNING")
    print("Status: PROVISIONAL_PENDING_HUMAN_REVIEW (Canonical Freeze: NOT_FROZEN)")
    print("=" * 75)

    git_sha = get_git_commit_sha()
    corpus_hash = compute_file_sha256(corpus_chunks_path)
    bench_hash = compute_file_sha256(benchmark_path)
    train_hash = compute_file_sha256(train_triples_path)

    # 1. Load Partition Lookup and Validate Training Data Guardrails
    print("Validating training data partition discipline...")
    partition_lookup = {}
    with open(partitioned_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                partition_lookup[d["chunk_id"]] = d["partition"]

    train_triples = []
    with open(train_triples_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                t = json.loads(line)
                validate_training_triple(t, chunk_partition_lookup=partition_lookup)
                train_triples.append(t)
    print(f"Verified {len(train_triples)} training triples from TRAIN partition.")

    # 2. Build Text Lookup for Positives
    print("Loading corpus texts for positive training passages...")
    corpus_text_lookup = {}
    with open(corpus_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                corpus_text_lookup[c["chunk_id"]] = format_chunk_text(c, include_breadcrumb=True)

    anchors = []
    positives = []
    for t in train_triples:
        pos_id = t["positive_chunk_id"]
        anchors.append(t["query_text"])
        positives.append(corpus_text_lookup[pos_id])

    train_dataset = Dataset.from_dict({
        "anchor": anchors,
        "positive": positives,
    })
    print(f"Prepared training dataset with {len(train_dataset)} pairs.")

    # 3. Initialize Model and Loss
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Initializing base model 'BAAI/bge-small-en-v1.5' on {device}...")
    model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
    loss = MultipleNegativesRankingLoss(model)

    # 4. Training Arguments and Trainer
    output_dir = Path(checkpoint_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = SentenceTransformerTrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=0.1,
        fp16=(device == "cuda"),
        logging_steps=5,
        save_strategy="no",
        report_to="none",
    )

    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        loss=loss,
    )

    print(f"\nStarting fine-tuning: epochs={epochs}, batch_size={batch_size}, lr={lr}...")
    t_train_start = time.perf_counter()
    trainer.train()
    train_elapsed = time.perf_counter() - t_train_start
    print(f"Fine-tuning complete in {train_elapsed:.2f}s.")

    # Save fine-tuned checkpoint
    final_model_path = output_dir / "final"
    model.save_pretrained(str(final_model_path))
    print(f"Saved fine-tuned checkpoint to: {final_model_path}")

    # 5. Evaluate Fine-Tuned Model on Candidate Benchmark v0
    print("\n" + "=" * 75)
    print("EVALUATING FINE-TUNED MODEL (E3-BGE-FT-v0-candidate) ON BENCHMARK v0")
    print("=" * 75)

    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    for q in queries:
        validate_validation_query(q)

    # Re-index corpus with fine-tuned model
    ft_retriever = DenseRetriever(
        model_name_or_path=str(final_model_path),
        batch_size=64,
        query_instruction="Represent this sentence for searching relevant passages: ",
    )
    # Overwrite cache for the fine-tuned checkpoint
    ft_retriever.build_index(corpus_chunks_path, cache_dir=str(output_dir / "index"), overwrite=True)

    # Run search on candidate benchmark
    individual_latencies: List[float] = []
    predictions: List[Dict[str, Any]] = []

    t_eval_start = time.perf_counter()
    for q in queries:
        retrieved_ids, scores, lat_ms = ft_retriever.search(
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

    p50_lat = float(np.percentile(individual_latencies, 50))
    p95_lat = float(np.percentile(individual_latencies, 95))
    p99_lat = float(np.percentile(individual_latencies, 99))
    mean_lat = float(np.mean(individual_latencies))
    qps = float(len(queries) / total_eval_elapsed)

    peak_vram_mb = float(torch.cuda.max_memory_allocated() / (1024 * 1024)) if torch.cuda.is_available() else 0.0

    latency_telemetry = {
        "total_queries": len(queries),
        "total_elapsed_sec": total_eval_elapsed,
        "queries_per_sec": qps,
        "mean_latency_ms": mean_lat,
        "p50_latency_ms": p50_lat,
        "p95_latency_ms": p95_lat,
        "p99_latency_ms": p99_lat,
        "peak_vram_allocated_mb": peak_vram_mb,
        "training_time_sec": train_elapsed,
    }

    # 6. Evaluation Metrics
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
        positives_set = {r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] >= 2}
        canonical_id = next((r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3), None)
        graded_rel = {r["chunk_id"]: r["grade"] for r in q["relevant_chunks"]}

        r1 = recall_at_k(retrieved, positives_set, k=1)
        r5 = recall_at_k(retrieved, positives_set, k=5)
        r10 = recall_at_k(retrieved, positives_set, k=10)
        r20 = recall_at_k(retrieved, positives_set, k=20)
        mrr = mrr_at_k(retrieved, positives_set, k=10)
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

        hits_50 = [cid for cid in retrieved[:50] if cid in positives_set]
        hits_10 = [cid for cid in retrieved[:10] if cid in positives_set]

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
            "total_positives": len(positives_set),
            "latency_ms": p["latency_ms"],
        }
        per_query_results.append(query_eval)

        if status != "SUCCESS":
            failures.append({
                "query_id": qid,
                "domain": domain,
                "typology": typology,
                "provenance_type": provenance,
                "query_text": q["query_text"],
                "failure_type": status,
                "source_partition": "validation",
                "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
                "canonical_chunk_id": canonical_id,
                "canonical_rank": canonical_rank,
                "positive_chunk_ids": list(positives_set),
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

    n_total = len(queries)
    aggregate_metrics = {
        "recall_at_1": float(np.mean(overall_r1)),
        "recall_at_5": float(np.mean(overall_r5)),
        "recall_at_10": float(np.mean(overall_r10)),
        "recall_at_20": float(np.mean(overall_r20)),
        "mrr_at_10": float(np.mean(overall_mrr10)),
        "ndcg_at_10": float(np.mean(overall_ndcg10)),
    }

    # 7. Persist Manifest
    manifest_data = {
        "experiment_id": "E3-BGE-FT-v0-candidate",
        "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
        "canonical_status": "NOT_FROZEN",
        "description": "Provisional Contrastive Fine-Tuned BGE-small on TRAIN partition",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit_sha": git_sha,
        "base_model": "BAAI/bge-small-en-v1.5",
        "training_data_path": train_triples_path,
        "training_data_sha256": train_hash,
        "training_data_partition": "train",
        "training_hyperparameters": {
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": lr,
            "loss": "MultipleNegativesRankingLoss",
            "training_time_sec": train_elapsed,
        },
        "corpus_chunks_path": corpus_chunks_path,
        "corpus_chunks_sha256": corpus_hash,
        "benchmark_v0_path": benchmark_path,
        "benchmark_v0_sha256": bench_hash,
        "benchmark_source_partition": "validation",
        "total_queries": n_total,
        "overall_metrics": aggregate_metrics,
        "latency_telemetry": latency_telemetry,
        "failure_summary": {
            "total_failures_top10": len(failures),
            "failure_rate_top10": float(len(failures) / n_total),
            "failures_top50": sum(1 for f in failures if f["failure_type"] == "RETRIEVAL_FAILURE_TOP50"),
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
        "experiment_id": "E3-BGE-FT-v0-candidate",
        "status": "PROVISIONAL_PENDING_HUMAN_REVIEW",
        "canonical_status": "NOT_FROZEN",
        "timestamp_utc": manifest_data["timestamp_utc"],
        "git_commit_sha": git_sha,
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
        },
        "per_query_results": per_query_results,
    }

    Path(metrics_path).parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(full_metrics_report, f, indent=2)

    print("\n" + "=" * 75)
    print("E3-BGE-FT-v0-candidate BENCHMARK SUMMARY (N=140)")
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
    print(f"Train Time: {train_elapsed:.2f} s")
    print(f"Failures:   {len(failures)} / {n_total} queries ({len(failures)/n_total*100:.1f}%)")
    print("=" * 75)

    return full_metrics_report


if __name__ == "__main__":
    run_e3_finetune()
