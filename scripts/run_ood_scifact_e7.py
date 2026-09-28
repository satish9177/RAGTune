"""Evaluate provisional E7 domain reranker on BEIR SciFact OOD Development Split.

Validates that in-domain cross-encoder training did not cause catastrophic forgetting
or out-of-domain degradation.
Candidate Pool: E5C Hybrid (BM25 + E4C Dense RRF k=60) Top-20 candidates.
Non-degradation gate: Delta NDCG@10 >= -0.015.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Set, Tuple

from datasets import load_dataset
import numpy as np
import scipy.stats
from sentence_transformers import CrossEncoder, SentenceTransformer
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.evaluation.metrics import mrr_at_k, ndcg_at_k, paired_bootstrap_delta, recall_at_k
from ragtune.retrieval.hybrid_retriever import reciprocal_rank_fusion


def sanitize_query_for_fts(query_text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query_text.lower())
    tokens = [t for t in tokens if len(t) > 0]
    if not tokens:
        return ""
    unique = []
    seen = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(f'"{t}"')
    return " OR ".join(unique)


def evaluate_ranking(
    query_ids: List[str],
    predictions: Dict[str, List[str]],
    qrels: Dict[str, Dict[str, int]],
) -> Dict[str, float]:
    r10_list, r20_list, r100_list = [], [], []
    ndcg10_list, mrr10_list = [], []

    for qid in query_ids:
        ret = predictions.get(qid, [])
        rel = qrels.get(qid, {})
        pos = {doc_id for doc_id, g in rel.items() if g > 0}

        r10 = recall_at_k(ret, pos, k=10)
        r20 = recall_at_k(ret, pos, k=20)
        r100 = recall_at_k(ret, pos, k=100)
        ndcg10 = ndcg_at_k(ret, rel, k=10)
        mrr10 = mrr_at_k(ret, pos, k=10)

        r10_list.append(r10)
        r20_list.append(r20)
        r100_list.append(r100)
        ndcg10_list.append(ndcg10)
        mrr10_list.append(mrr10)

    return {
        "recall_at_10": float(np.mean(r10_list)),
        "recall_at_20": float(np.mean(r20_list)),
        "recall_at_100": float(np.mean(r100_list)),
        "ndcg_at_10": float(np.mean(ndcg10_list)),
        "mrr_at_10": float(np.mean(mrr10_list)),
        "num_queries": len(query_ids),
    }


def main():
    print("=" * 80)
    print("OOD SCIFACT EVALUATION FOR E7 DOMAIN RERANKER")
    print("=" * 80)

    root = Path(__file__).resolve().parent.parent
    db_path = root / "data" / "indices" / "scifact_fts.db"
    e4c_model_path = root / "data" / "models" / "e4c_bge_matchedeasy_v0" / "final"
    e7_model_path = root / "data" / "models" / "e7_bge_reranker_provisional_v0"

    out_metrics_path = root / "benchmarks" / "experiments" / "ood_scifact_e7_metrics.json"
    out_manifest_path = root / "benchmarks" / "experiments" / "ood_scifact_e7_manifest.json"

    # 1. Load BEIR SciFact
    print("Loading BEIR SciFact dataset from HuggingFace...")
    ds_corpus = load_dataset("mteb/scifact", "corpus", split="corpus")
    ds_queries = load_dataset("mteb/scifact", "queries", split="queries")
    ds_qrels = load_dataset("mteb/scifact", "default", split="test")

    qrels: Dict[str, Dict[str, int]] = {}
    for r in ds_qrels:
        qid = str(r["query-id"])
        cid = str(r["corpus-id"])
        grade = int(r["score"])
        if qid not in qrels:
            qrels[qid] = {}
        qrels[qid][cid] = grade

    query_lookup = {str(q["_id"]): q["text"] for q in ds_queries}
    test_qids = sorted([qid for qid in qrels if qid in query_lookup])
    print(f"Loaded {len(test_qids)} test queries with ground-truth qrels.")

    corpus_lookup = {
        str(item["_id"]): f"{item.get('title', '')} {item.get('text', '')}".strip()
        for item in ds_corpus
    }
    corpus_ids = [str(item["_id"]) for item in ds_corpus]
    corpus_texts = [corpus_lookup[cid] for cid in corpus_ids]

    # 2. Retrieve BM25 candidates
    print("Querying BM25 index on SciFact...")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    bm25_preds: Dict[str, List[str]] = {}
    for qid in test_qids:
        qtext = query_lookup[qid]
        fts_query = sanitize_query_for_fts(qtext)
        if not fts_query:
            bm25_preds[qid] = []
            continue
        try:
            cur.execute("""
                SELECT doc_id, bm25(scifact_fts, 2.0, 1.0) as score
                FROM scifact_fts
                WHERE scifact_fts MATCH ?
                ORDER BY score ASC
                LIMIT 50
            """, (fts_query,))
            bm25_preds[qid] = [r["doc_id"] for r in cur.fetchall()]
        except Exception:
            bm25_preds[qid] = []
    conn.close()

    # 3. Dense Retrieval with E4C
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading E4C dense model from {e4c_model_path} on {device}...")
    st_model = SentenceTransformer(
        str(e4c_model_path),
        device=device,
        model_kwargs={"torch_dtype": torch.float16 if device == "cuda" else torch.float32},
    )
    st_model.eval()

    print("Encoding SciFact corpus...")
    c_embs = st_model.encode(
        corpus_texts,
        batch_size=128,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_tensor=True,
        device=device,
    )

    query_instruction = "Represent this sentence for searching relevant passages: "
    test_query_texts = [f"{query_instruction}{query_lookup[qid]}" for qid in test_qids]

    print("Encoding queries...")
    q_embs = st_model.encode(
        test_query_texts,
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_tensor=True,
        device=device,
    )

    scores = torch.matmul(q_embs, c_embs.T)
    top50_vals, top50_indices = torch.topk(scores, k=min(50, len(corpus_ids)), dim=1)
    top50_cpu = top50_indices.cpu().numpy()

    dense_e4c_preds: Dict[str, List[str]] = {}
    for idx, qid in enumerate(test_qids):
        dense_e4c_preds[qid] = [corpus_ids[doc_idx] for doc_idx in top50_cpu[idx]]

    del st_model, c_embs, q_embs, scores
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # 4. Construct Stage-1 E5C Hybrid (RRF k=60)
    print("Fusing BM25 + E4C Dense into E5C Hybrid...")
    e5c_preds: Dict[str, List[str]] = {}
    e5c_per_query_ndcg: List[float] = []

    for qid in test_qids:
        b_list = bm25_preds.get(qid, [])
        d_list = dense_e4c_preds.get(qid, [])
        fused_ids, _ = reciprocal_rank_fusion([b_list, d_list], rrf_k=60, top_k=50)
        e5c_preds[qid] = fused_ids
        e5c_per_query_ndcg.append(ndcg_at_k(fused_ids, qrels[qid], k=10))

    # 5. Rerank E5C Top-20 with E7 Domain Reranker
    print(f"Loading E7 Domain Reranker from {e7_model_path} on {device}...")
    reranker = CrossEncoder(str(e7_model_path), device=device, max_length=384)

    candidate_depth = 20
    e7_preds: Dict[str, List[str]] = {}
    e7_per_query_ndcg: List[float] = []

    t_rerank_start = time.perf_counter()
    for qid in test_qids:
        qtext = query_lookup[qid]
        s1_cands = e5c_preds[qid][:candidate_depth]
        tail_cands = e5c_preds[qid][candidate_depth:]

        pairs = [(qtext, corpus_lookup.get(cid, "")) for cid in s1_cands]
        scores = reranker.predict(pairs, batch_size=candidate_depth, show_progress_bar=False, convert_to_numpy=True)
        scored_pairs = sorted(zip(s1_cands, scores), key=lambda x: x[1], reverse=True)
        reranked_ids = [c for c, _ in scored_pairs] + tail_cands

        e7_preds[qid] = reranked_ids
        e7_per_query_ndcg.append(ndcg_at_k(reranked_ids, qrels[qid], k=10))

    rerank_time = time.perf_counter() - t_rerank_start

    # 6. Evaluate Metrics
    e5c_metrics = evaluate_ranking(test_qids, e5c_preds, qrels)
    e7_metrics = evaluate_ranking(test_qids, e7_preds, qrels)

    # 7. Statistical Test: E7 vs E5C on SciFact
    e7_ndcg_arr = np.array(e7_per_query_ndcg)
    e5c_ndcg_arr = np.array(e5c_per_query_ndcg)
    obs_delta, ci_low, ci_high = paired_bootstrap_delta(e7_ndcg_arr, e5c_ndcg_arr, num_resamples=5000, seed=42)

    # Predeclared non-degradation threshold: delta >= -0.015
    is_non_degraded = obs_delta >= -0.015 and ci_high >= -0.020

    print("\n" + "=" * 80)
    print("OOD SCIFACT EVALUATION RESULTS:")
    print("=" * 80)
    print(f"{'Metric':<15} | {'E5C Stage-1':<15} | {'E7 Reranker':<15} | {'Delta':<10}")
    print("-" * 60)
    print(f"{'NDCG@10':<15} | {e5c_metrics['ndcg_at_10']:<15.4f} | {e7_metrics['ndcg_at_10']:<15.4f} | {obs_delta:+.4f}")
    print(f"{'Recall@10':<15} | {e5c_metrics['recall_at_10']:<15.4f} | {e7_metrics['recall_at_10']:<15.4f} | {e7_metrics['recall_at_10']-e5c_metrics['recall_at_10']:+.4f}")
    print(f"{'MRR@10':<15} | {e5c_metrics['mrr_at_10']:<15.4f} | {e7_metrics['mrr_at_10']:<15.4f} | {e7_metrics['mrr_at_10']-e5c_metrics['mrr_at_10']:+.4f}")
    print(f"\nPaired 95% Bootstrap CI: [{ci_low:+.4f}, {ci_high:+.4f}]")
    print(f"OOD Non-Degradation Verdict: {'PASS' if is_non_degraded else 'FAIL'} (Gate: Delta >= -0.015)")
    print("=" * 80)

    # Persist outputs
    out_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_payload = {
        "benchmark": "BEIR/SciFact (mteb/scifact)",
        "split": "test",
        "num_queries": len(test_qids),
        "e5c_baseline": e5c_metrics,
        "e7_reranked": e7_metrics,
        "comparison_e7_vs_e5c": {
            "observed_delta_ndcg10": obs_delta,
            "ci_95_lower": ci_low,
            "ci_95_upper": ci_high,
            "non_degradation_gate": "PASSED" if is_non_degraded else "FAILED",
            "threshold": -0.015,
        },
        "timing": {
            "rerank_total_sec": rerank_time,
            "queries_per_sec": len(test_qids) / rerank_time,
        },
    }

    with open(out_metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"Persisted OOD metrics to: {out_metrics_path.name}")

    manifest_payload = {
        "experiment_id": "OOD-SciFact-E7-Eval-v0",
        "status": "COMPLETED",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model_path": str(e7_model_path.relative_to(root)),
        "candidate_depth": candidate_depth,
        "metrics": e7_metrics,
        "gate_verdict": "PASSED" if is_non_degraded else "FAILED",
    }
    with open(out_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_payload, f, indent=2)
    print(f"Persisted OOD manifest to: {out_manifest_path.name}")


if __name__ == "__main__":
    main()
