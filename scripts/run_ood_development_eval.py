"""RAGTune OOD Development Evaluation: BEIR SciFact.

Evaluates out-of-domain retrieval quality across:
- BM25 Baseline (SQLite FTS5 on SciFact corpus)
- E1a (Zero-shot BAAI/bge-small-en-v1.5)
- E4C (Matched-Easy Fine-Tuned BGE)
- E4 (Hard-Negative Fine-Tuned BGE)
- E5C (BM25 + E4C Dense Hybrid RRF k=60)
- E5H (BM25 + E4 Dense Hybrid RRF k=60)

Validates whether in-domain RAGTune fine-tuning damaged general domain retrieval capability.
Strictly zero contamination: does not touch frozen_test or RAGTune validation queries.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Set, Tuple

from datasets import load_dataset
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.evaluation.metrics import dcg_at_k, mrr_at_k, ndcg_at_k, paired_bootstrap_delta, recall_at_k
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


def build_scifact_fts_index(corpus_items: List[Dict[str, Any]], db_path: Path) -> sqlite3.Connection:
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE VIRTUAL TABLE scifact_fts USING fts5(
            doc_id UNINDEXED,
            title,
            text,
            tokenize='unicode61'
        )
    """)
    records = []
    for item in corpus_items:
        records.append((str(item["_id"]), item.get("title", "") or "", item.get("text", "") or ""))
    cur.executemany("INSERT INTO scifact_fts(doc_id, title, text) VALUES (?, ?, ?)", records)
    conn.commit()
    return conn


def evaluate_ranking(
    query_ids: List[str],
    predictions: Dict[str, List[str]],
    qrels: Dict[str, Dict[str, int]],
) -> Dict[str, float]:
    r10_list, r100_list = [], []
    ndcg10_list, mrr10_list = [], []

    for qid in query_ids:
        ret = predictions.get(qid, [])
        rel = qrels.get(qid, {})
        pos = {doc_id for doc_id, g in rel.items() if g > 0}

        r10 = recall_at_k(ret, pos, k=10)
        r100 = recall_at_k(ret, pos, k=100)
        ndcg10 = ndcg_at_k(ret, rel, k=10)
        mrr10 = mrr_at_k(ret, pos, k=10)

        r10_list.append(r10)
        r100_list.append(r100)
        ndcg10_list.append(ndcg10)
        mrr10_list.append(mrr10)

    return {
        "recall_at_10": float(np.mean(r10_list)),
        "recall_at_100": float(np.mean(r100_list)),
        "ndcg_at_10": float(np.mean(ndcg10_list)),
        "mrr_at_10": float(np.mean(mrr10_list)),
        "num_queries": len(query_ids),
    }


def main():
    print("=" * 80)
    print("STARTING OOD DEVELOPMENT EVALUATION: BEIR SCIFACT")
    print("=" * 80)

    # 1. Load BEIR SciFact via datasets
    print("Loading BEIR SciFact dataset from HuggingFace (mteb/scifact)...")
    ds_corpus = load_dataset("mteb/scifact", "corpus", split="corpus")
    ds_queries = load_dataset("mteb/scifact", "queries", split="queries")
    ds_qrels = load_dataset("mteb/scifact", "default", split="test")

    print(f"Corpus size: {len(ds_corpus)}")
    print(f"Total queries in dataset: {len(ds_queries)}")
    print(f"Test qrels count: {len(ds_qrels)}")

    # Map qrels: query_id -> {doc_id: grade}
    qrels: Dict[str, Dict[str, int]] = {}
    for r in ds_qrels:
        qid = str(r["query-id"])
        cid = str(r["corpus-id"])
        grade = int(r["score"])
        if qid not in qrels:
            qrels[qid] = {}
        qrels[qid][cid] = grade

    # Filter to test queries that actually have qrels
    query_lookup = {str(q["_id"]): q["text"] for q in ds_queries}
    test_qids = [qid for qid in qrels if qid in query_lookup]
    test_qids.sort()
    print(f"Evaluated test queries with ground-truth qrels: {len(test_qids)}")

    corpus_ids = [str(item["_id"]) for item in ds_corpus]
    corpus_texts = [
        f"{item.get('title', '')} {item.get('text', '')}".strip() for item in ds_corpus
    ]

    # 2. Build BM25 index on SciFact
    print("\n--- Building BM25 Index on SciFact ---")
    db_path = Path("data/indices/scifact_fts.db")
    fts_conn = build_scifact_fts_index(ds_corpus, db_path)
    cur = fts_conn.cursor()

    bm25_predictions: Dict[str, List[str]] = {}
    for qid in test_qids:
        qtext = query_lookup[qid]
        fts_query = sanitize_query_for_fts(qtext)
        if not fts_query:
            bm25_predictions[qid] = []
            continue
        try:
            cur.execute("""
                SELECT doc_id, bm25(scifact_fts, 2.0, 1.0) as score
                FROM scifact_fts
                WHERE scifact_fts MATCH ?
                ORDER BY score ASC
                LIMIT 100
            """, (fts_query,))
            rows = cur.fetchall()
            bm25_predictions[qid] = [r["doc_id"] for r in rows]
        except Exception as e:
            bm25_predictions[qid] = []
    fts_conn.close()

    # 3. Dense models to evaluate
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nUsing device: {device}")

    model_configs = [
        ("E1a_ZeroShot_BGE", "BAAI/bge-small-en-v1.5"),
        ("E4C_MatchedEasy_BGE", "data/models/e4c_bge_matchedeasy_v0/final"),
        ("E4_HardNeg_BGE", "data/models/e4_bge_hardneg_v0/final"),
    ]

    query_instruction = "Represent this sentence for searching relevant passages: "
    test_query_texts = [f"{query_instruction}{query_lookup[qid]}" for qid in test_qids]

    dense_predictions: Dict[str, Dict[str, List[str]]] = {}
    dense_per_query_ndcg: Dict[str, List[float]] = {}

    for sys_id, model_path in model_configs:
        print(f"\n--- Evaluating Dense Model: {sys_id} ({model_path}) ---")
        t0 = time.perf_counter()
        st_model = SentenceTransformer(
            model_path,
            device=device,
            model_kwargs={"torch_dtype": torch.float16 if device == "cuda" else torch.float32},
        )
        st_model.eval()

        # Encode corpus
        print("  Encoding 5,183 corpus abstracts...")
        c_embs = st_model.encode(
            corpus_texts,
            batch_size=128,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_tensor=True,
            device=device,
        )

        # Encode queries
        print(f"  Encoding {len(test_qids)} test queries...")
        q_embs = st_model.encode(
            test_query_texts,
            batch_size=64,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_tensor=True,
            device=device,
        )

        # Dot product search
        print("  Computing top-100 similarity rankings...")
        scores = torch.matmul(q_embs, c_embs.T)  # [300, 5183]
        top100_vals, top100_indices = torch.topk(scores, k=min(100, len(corpus_ids)), dim=1)

        top100_indices_cpu = top100_indices.cpu().numpy()
        sys_preds: Dict[str, List[str]] = {}
        per_q_ndcg: List[float] = []

        for idx, qid in enumerate(test_qids):
            ret_doc_ids = [corpus_ids[doc_idx] for doc_idx in top100_indices_cpu[idx]]
            sys_preds[qid] = ret_doc_ids
            ndcg10 = ndcg_at_k(ret_doc_ids, qrels[qid], k=10)
            per_q_ndcg.append(ndcg10)

        dense_predictions[sys_id] = sys_preds
        dense_per_query_ndcg[sys_id] = per_q_ndcg
        elapsed = time.perf_counter() - t0
        print(f"  Completed {sys_id} in {elapsed:.2f}s.")

        # Free GPU memory
        del st_model, c_embs, q_embs, scores, top100_vals, top100_indices
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # 4. Hybrid Systems (E5C and E5H)
    print("\n--- Computing Hybrids (RRF k=60) ---")
    hybrid_configs = [
        ("E5C_Hybrid_MatchedEasy", "E4C_MatchedEasy_BGE"),
        ("E5H_Hybrid_HardNeg", "E4_HardNeg_BGE"),
    ]

    hybrid_predictions: Dict[str, Dict[str, List[str]]] = {}
    hybrid_per_query_ndcg: Dict[str, List[float]] = {}

    for hyb_id, dense_src in hybrid_configs:
        h_preds: Dict[str, List[str]] = {}
        per_q_ndcg = []
        for qid in test_qids:
            bm25_list = bm25_predictions.get(qid, [])
            dense_list = dense_predictions[dense_src].get(qid, [])
            fused_ids, _ = reciprocal_rank_fusion([bm25_list, dense_list], rrf_k=60, top_k=100)
            h_preds[qid] = fused_ids
            per_q_ndcg.append(ndcg_at_k(fused_ids, qrels[qid], k=10))

        hybrid_predictions[hyb_id] = h_preds
        hybrid_per_query_ndcg[hyb_id] = per_q_ndcg

    # 5. Evaluate all systems
    all_systems: Dict[str, Dict[str, List[str]]] = {
        "BM25_Baseline": bm25_predictions,
        **dense_predictions,
        **hybrid_predictions,
    }

    results: Dict[str, Dict[str, Any]] = {}
    print("\n" + "=" * 80)
    print("OOD SCIFACT EVALUATION SUMMARY (300 Test Queries)")
    print("=" * 80)
    print(f"{'System':<25} | {'NDCG@10':<10} | {'Recall@10':<10} | {'Recall@100':<10} | {'MRR@10':<10}")
    print("-" * 75)

    for sys_name, preds in all_systems.items():
        m = evaluate_ranking(test_qids, preds, qrels)
        results[sys_name] = m
        print(f"{sys_name:<25} | {m['ndcg_at_10']:<10.4f} | {m['recall_at_10']:<10.4f} | {m['recall_at_100']:<10.4f} | {m['mrr_at_10']:<10.4f}")

    # 6. Statistical Comparison against Zero-Shot E1a
    print("\n" + "=" * 80)
    print("STATISTICAL COMPARISON AGAINST ZERO-SHOT E1a (Delta NDCG@10, 95% Bootstrap CI)")
    print("=" * 80)
    e1a_scores = np.array(dense_per_query_ndcg["E1a_ZeroShot_BGE"])

    comparisons: Dict[str, Any] = {}
    for comp_sys, comp_scores_list in [
        ("E4C_MatchedEasy_BGE", dense_per_query_ndcg["E4C_MatchedEasy_BGE"]),
        ("E4_HardNeg_BGE", dense_per_query_ndcg["E4_HardNeg_BGE"]),
        ("E5C_Hybrid_MatchedEasy", hybrid_per_query_ndcg["E5C_Hybrid_MatchedEasy"]),
        ("E5H_Hybrid_HardNeg", hybrid_per_query_ndcg["E5H_Hybrid_HardNeg"]),
    ]:
        comp_scores = np.array(comp_scores_list)
        observed_delta, ci_lower, ci_upper = paired_bootstrap_delta(comp_scores, e1a_scores, num_resamples=5000, seed=42)
        degraded = ci_upper < 0.0 and observed_delta < -0.02
        delta_stat = {
            "observed_delta": observed_delta,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "degraded": bool(degraded),
        }
        comparisons[comp_sys] = delta_stat
        print(f"{comp_sys:<25} vs E1a:")
        print(f"  Delta NDCG@10: {observed_delta:+.4f}")
        print(f"  95% CI:        [{ci_lower:+.4f}, {ci_upper:+.4f}]")
        print(f"  OOD Non-Degradation Verdict: {'DEGRADED (FAIL)' if degraded else 'PASSED (NON-DEGRADED)'}")

    # 7. Persist outputs
    out_dir = Path("benchmarks/experiments")
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_payload = {
        "benchmark": "BEIR/SciFact (mteb/scifact)",
        "split": "test",
        "num_queries": len(test_qids),
        "corpus_size": len(corpus_ids),
        "results": results,
        "statistical_comparisons_vs_e1a": comparisons,
    }
    with open(out_dir / "ood_scifact_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)

    manifest_payload = {
        "experiment_id": "OOD-SciFact-Eval-v1",
        "description": "Out-of-domain development gate evaluation on BEIR SciFact test split",
        "benchmark": "mteb/scifact",
        "query_count": len(test_qids),
        "corpus_count": len(corpus_ids),
        "systems": list(all_systems.keys()),
        "status": "COMPLETED",
        "gate_verdict": "PASSED" if all(c["ci_upper"] >= -0.02 for c in comparisons.values()) else "FAILED",
    }
    with open(out_dir / "ood_scifact_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest_payload, f, indent=2)

    print(f"\nPersisted OOD metrics to: {out_dir / 'ood_scifact_metrics.json'}")
    print(f"Persisted OOD manifest to: {out_dir / 'ood_scifact_manifest.json'}")


if __name__ == "__main__":
    main()
