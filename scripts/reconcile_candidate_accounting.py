"""Reconcile all 10,669 mined candidates into an exhaustive mutually exclusive disposition table."""

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

import re
from ragtune.retrieval.dense_retriever import format_chunk_text
from ragtune.retrieval.lexical_retriever import sanitize_query_to_fts5


def compute_jaccard(text1: str, text2: str) -> float:
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union if union > 0 else 0.0


def main():
    print("Starting exact candidate disposition accounting...")
    partitioned_chunks_path = "data/processed/partitioned_chunks.jsonl"
    input_queries_path = "data/training/hard_negative_audit_v0.jsonl"

    partition_lookup = {}
    train_chunks = []
    chunk_by_id = {}

    with open(partitioned_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            cid = c["chunk_id"]
            part = c["partition"]
            partition_lookup[cid] = part
            chunk_by_id[cid] = c
            if part == "train":
                train_chunks.append(c)

    db = sqlite3.connect(":memory:")
    cur = db.cursor()
    cur.execute("""
        CREATE VIRTUAL TABLE train_fts USING fts5(
            chunk_id UNINDEXED,
            ecosystem UNINDEXED,
            content,
            tokenize='unicode61'
        )
    """)
    for c in train_chunks:
        text = format_chunk_text(c, include_breadcrumb=True)
        cur.execute(
            "INSERT INTO train_fts(chunk_id, ecosystem, content) VALUES (?, ?, ?)",
            (c["chunk_id"], c["ecosystem"].lower(), text),
        )
    db.commit()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dense_model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)

    train_texts = [format_chunk_text(c, include_breadcrumb=True) for c in train_chunks]
    train_chunk_ids = [c["chunk_id"] for c in train_chunks]
    train_embeddings = dense_model.encode(
        train_texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_tensor=True,
        device=device,
    )

    queries: List[Dict[str, Any]] = []
    seen_qids = set()
    with open(input_queries_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            qid = entry["query_id"]
            if qid not in seen_qids:
                seen_qids.add(qid)
                queries.append(entry)

    query_texts = [q["query_text"] for q in queries]
    query_embeddings = dense_model.encode(
        query_texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_tensor=True,
        device=device,
    )

    raw_candidates_by_query: Dict[str, Dict[str, Any]] = {}
    total_mined = 0

    for i, q in enumerate(queries):
        qid = q["query_id"]
        pos_id = q["positive_chunk_id"]
        qtext = q["query_text"]
        domain = q["domain"].lower()

        candidates: Dict[str, Dict[str, Any]] = {}

        # BM25
        sanitized = sanitize_query_to_fts5(qtext)
        if sanitized:
            cur.execute(
                "SELECT chunk_id, bm25(train_fts) as score FROM train_fts WHERE train_fts MATCH ? AND ecosystem = ? ORDER BY score LIMIT 10",
                (sanitized, domain),
            )
            rows = cur.fetchall()
            for rank, r in enumerate(rows, start=1):
                cid = r[0]
                candidates[cid] = {
                    "chunk_id": cid,
                    "retrievers": ["bm25"],
                    "lexical_rank": rank,
                    "dense_rank": None,
                    "lexical_score": float(r[1]),
                }

        # Dense
        q_emb = query_embeddings[i : i + 1]
        sims = torch.mm(q_emb, train_embeddings.t()).squeeze(0)
        top_scores, top_indices = torch.topk(sims, k=15)
        top_scores = top_scores.cpu().tolist()
        top_indices = top_indices.cpu().tolist()

        for rank, (score, idx) in enumerate(zip(top_scores, top_indices), start=1):
            cid = train_chunk_ids[idx]
            if chunk_by_id[cid]["ecosystem"].lower() != domain:
                continue
            if cid in candidates:
                candidates[cid]["retrievers"].append("dense_bge")
                candidates[cid]["dense_rank"] = rank
                candidates[cid]["dense_score"] = float(score)
            else:
                candidates[cid] = {
                    "chunk_id": cid,
                    "retrievers": ["dense_bge"],
                    "lexical_rank": None,
                    "dense_rank": rank,
                    "dense_score": float(score),
                }

        raw_candidates_by_query[qid] = candidates
        total_mined += len(candidates)

    print(f"Total raw candidates mined: {total_mined}")

    # Teacher scoring
    teacher = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512)
    pairs_to_score = []
    pair_meta = []

    rejected_known_positive = 0
    quarantined_same_doc = 0
    quarantined_high_overlap = 0

    disposition_counts = {
        "known_positive_exclusions": 0,
        "quarantined_same_document_subtopic": 0,
        "quarantined_high_lexical_overlap": 0,
        "quarantined_teacher_inversion": 0,
        "quarantined_high_teacher_score": 0,
        "quarantined_ambiguous_margin": 0,
        "accepted_training_negatives": 0,
        "pruned_excess_eligible_quota_exceeded": 0,
        "rejected_low_positive_teacher_score": 0,
    }

    for q in queries:
        qid = q["query_id"]
        pos_id = q["positive_chunk_id"]
        pos_chunk = chunk_by_id[pos_id]
        pos_text = format_chunk_text(pos_chunk, include_breadcrumb=True)
        pos_path = pos_chunk.get("relative_file_path", "")
        pos_bc = pos_chunk.get("breadcrumb", "")
        qtext = q["query_text"]

        pairs_to_score.append((qtext, pos_text))
        pair_meta.append({"is_positive": True, "query_id": qid, "chunk_id": pos_id})

        candidates = raw_candidates_by_query.get(qid, {})
        for cid, cinfo in candidates.items():
            if cid == pos_id:
                disposition_counts["known_positive_exclusions"] += 1
                continue

            neg_chunk = chunk_by_id[cid]
            neg_text = format_chunk_text(neg_chunk, include_breadcrumb=True)
            neg_path = neg_chunk.get("relative_file_path", "")
            neg_bc = neg_chunk.get("breadcrumb", "")

            jaccard = compute_jaccard(pos_text, neg_text)
            if pos_path == neg_path and (jaccard > 0.35 or (pos_bc and pos_bc == neg_bc)):
                disposition_counts["quarantined_same_document_subtopic"] += 1
                continue

            if jaccard > 0.40:
                disposition_counts["quarantined_high_lexical_overlap"] += 1
                continue

            pairs_to_score.append((qtext, neg_text))
            pair_meta.append({
                "is_positive": False,
                "query_id": qid,
                "chunk_id": cid,
                "dense_rank": cinfo["dense_rank"],
                "lexical_rank": cinfo["lexical_rank"],
            })

    print(f"Scoring {len(pairs_to_score)} pairs with teacher...")
    scores = teacher.predict(pairs_to_score, batch_size=64, show_progress_bar=False, convert_to_numpy=True)

    pos_scores = {}
    neg_candidates_scored = {}
    for meta, score in zip(pair_meta, scores):
        qid = meta["query_id"]
        score_val = float(score)
        if meta["is_positive"]:
            pos_scores[qid] = score_val
        else:
            meta["teacher_score"] = score_val
            if qid not in neg_candidates_scored:
                neg_candidates_scored[qid] = []
            neg_candidates_scored[qid].append(meta)

    for qid, cands in neg_candidates_scored.items():
        s_pos = pos_scores.get(qid, 0.0)
        cands.sort(key=lambda c: (
            c["dense_rank"] if c["dense_rank"] is not None else 999,
            c["lexical_rank"] if c["lexical_rank"] is not None else 999,
        ))

        chosen_for_query = 0
        for cand in cands:
            s_neg = cand["teacher_score"]
            margin = s_pos - s_neg

            if margin <= 0.0:
                disposition_counts["quarantined_teacher_inversion"] += 1
                continue
            if s_neg >= 0.60:
                disposition_counts["quarantined_high_teacher_score"] += 1
                continue
            if margin < 0.25:
                disposition_counts["quarantined_ambiguous_margin"] += 1
                continue

            # Eligible candidates
            if s_pos < 0.30:
                disposition_counts["rejected_low_positive_teacher_score"] += 1
            elif chosen_for_query < 2:
                disposition_counts["accepted_training_negatives"] += 1
                chosen_for_query += 1
            else:
                disposition_counts["pruned_excess_eligible_quota_exceeded"] += 1

    total_accounted = sum(disposition_counts.values())
    print("\n" + "=" * 80)
    print("EXHAUSTIVE MUTUALLY EXCLUSIVE DISPOSITION ACCOUNTING")
    print("=" * 80)
    for cat, count in disposition_counts.items():
        pct = (count / total_mined) * 100
        print(f"{cat:45}: {count:6d} ({pct:5.2f}%)")
    print("-" * 80)
    print(f"{'Total Accounted':45}: {total_accounted:6d}")
    print(f"{'Total Mined':45}: {total_mined:6d}")
    print(f"{'Discrepancy':45}: {total_accounted - total_mined:6d}")
    print("=" * 80)

    with open("data/training/hard_negative_candidate_disposition.json", "w", encoding="utf-8") as f:
        json.dump({
            "total_candidates_mined": total_mined,
            "total_accounted": total_accounted,
            "disposition_breakdown": disposition_counts,
        }, f, indent=2)


if __name__ == "__main__":
    main()
