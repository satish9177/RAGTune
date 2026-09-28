"""Mine verified hard negatives for E4-BGE-HardNeg-v0 within the TRAIN partition only.

False-Negative Protection Protocol:
1. Candidate Pool:
   - Retaining strict partition discipline: TRAIN partition only (0% validation, 0% frozen_test).
   - Multi-retriever mining: BM25 lexical retriever + BGE-small dense retriever over 6,414 TRAIN chunks.
2. Layered False-Negative Protection:
   - Layer 1 (Known Positives): Immediate exclusion of the positive chunk ID.
   - Layer 2 (Document Proximity): Candidates sharing same file and high lexical overlap (>0.35 Jaccard) or identical breadcrumb quarantined.
   - Layer 3 (Lexical Overlap): Candidates with >0.40 Jaccard similarity to positive quarantined.
   - Layer 4 (Teacher Cross-Encoder): BAAI/bge-reranker-base scoring:
     * Inverted scores (margin <= 0) quarantined (potential alternate answer / false negative).
     * High absolute scores (s_neg >= 0.70) quarantined (likely alternate ground truth).
     * Ambiguous scores (0 < margin < 0.20) quarantined.
     * Accepted verified hard negatives: margin >= 0.25, s_neg < 0.60, s_pos >= 0.30.
3. Outputs:
   - data/training/hard_negatives_v1.jsonl
   - data/training/hard_negative_quarantine_v1.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.retrieval.dense_retriever import format_chunk_text
from ragtune.retrieval.lexical_retriever import sanitize_query_to_fts5
from ragtune.training.guardrails import validate_training_triple


def compute_jaccard(text1: str, text2: str) -> float:
    """Compute word-level Jaccard similarity between two texts."""
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union if union > 0 else 0.0


def mine_hard_negatives(
    partitioned_chunks_path: str = "data/processed/partitioned_chunks.jsonl",
    input_queries_path: str = "data/training/hard_negative_audit_v0.jsonl",
    output_hard_negatives_path: str = "data/training/hard_negatives_v1.jsonl",
    output_quarantine_path: str = "data/training/hard_negative_quarantine_v1.jsonl",
    min_teacher_margin: float = 0.25,
    max_teacher_neg_score: float = 0.60,
    min_teacher_pos_score: float = 0.30,
) -> Dict[str, Any]:
    print("=" * 80)
    print("RAGTUNE HARD NEGATIVE MINING v1 (TRAIN Partition Discipline & False-Negative Shield)")
    print("=" * 80)

    # 1. Load partitioned chunks and isolate TRAIN partition
    print(f"Loading partitioned chunks from {partitioned_chunks_path}...")
    partition_lookup: Dict[str, str] = {}
    train_chunks: List[Dict[str, Any]] = []
    chunk_by_id: Dict[str, Dict[str, Any]] = {}

    with open(partitioned_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            cid = c["chunk_id"]
            part = c["partition"]
            partition_lookup[cid] = part
            if part == "train":
                train_chunks.append(c)
                chunk_by_id[cid] = c

    print(f"Loaded {len(train_chunks)} TRAIN chunks (total corpus chunks: {len(partition_lookup)}).")

    # 2. Build in-memory BM25 index on TRAIN chunks
    print("Building in-memory BM25 lexical index on TRAIN chunks...")
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
    print("In-memory BM25 index ready.")

    # 3. Dense Embeddings for TRAIN chunks using BGE-small
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Initializing dense retriever BAAI/bge-small-en-v1.5 on {device}...")
    dense_model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)

    print("Encoding TRAIN chunks for dense negative mining...")
    t0 = time.perf_counter()
    train_texts = [format_chunk_text(c, include_breadcrumb=True) for c in train_chunks]
    train_chunk_ids = [c["chunk_id"] for c in train_chunks]
    train_chunk_id_to_idx = {cid: idx for idx, cid in enumerate(train_chunk_ids)}
    train_embeddings = dense_model.encode(
        train_texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_tensor=True,
        device=device,
    )
    t_enc = time.perf_counter() - t0
    print(f"Dense embeddings encoded in {t_enc:.2f}s ({len(train_embeddings)} vectors).")

    # 4. Load input training queries
    print(f"Loading training queries from {input_queries_path}...")
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

    print(f"Loaded {len(queries)} distinct training queries.")

    # 5. Mine candidate negatives using BM25 and Dense
    print("\nMining candidate negatives per query (BM25 + Dense)...")
    raw_candidates_by_query: Dict[str, Dict[str, Dict[str, Any]]] = {}
    total_candidates_mined = 0

    query_texts = [q["query_text"] for q in queries]
    query_embeddings = dense_model.encode(
        query_texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_tensor=True,
        device=device,
    )

    for i, q in enumerate(queries):
        qid = q["query_id"]
        pos_id = q["positive_chunk_id"]
        qtext = q["query_text"]
        domain = q["domain"].lower()

        candidates: Dict[str, Dict[str, Any]] = {}

        # 5a. BM25 Retrieval
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

        # 5b. Dense Retrieval
        q_emb = query_embeddings[i : i + 1]
        sims = torch.mm(q_emb, train_embeddings.t()).squeeze(0)
        # Top 15 dense candidates
        top_scores, top_indices = torch.topk(sims, k=15)
        top_scores = top_scores.cpu().tolist()
        top_indices = top_indices.cpu().tolist()

        for rank, (score, idx) in enumerate(zip(top_scores, top_indices), start=1):
            cid = train_chunk_ids[idx]
            # Ensure domain matches
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
        total_candidates_mined += len(candidates)

    print(f"Mined {total_candidates_mined} total candidates across {len(queries)} queries.")

    # 6. False-Negative Filtering & Teacher Cross-Encoder Scoring
    print(f"\nInitializing Teacher Model 'BAAI/bge-reranker-base' on {device}...")
    teacher = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512)

    # Collect pairs to score with teacher
    pairs_to_score: List[Tuple[str, str]] = []
    pair_meta: List[Dict[str, Any]] = []

    rejected_known_positive = 0
    quarantined_same_doc = 0
    quarantined_high_overlap = 0

    quarantined_records: List[Dict[str, Any]] = []

    for q in queries:
        qid = q["query_id"]
        pos_id = q["positive_chunk_id"]
        pos_chunk = chunk_by_id[pos_id]
        pos_text = format_chunk_text(pos_chunk, include_breadcrumb=True)
        pos_path = pos_chunk.get("relative_file_path", "")
        pos_bc = pos_chunk.get("breadcrumb", "")
        qtext = q["query_text"]

        # Ensure positive itself is scored by teacher
        pairs_to_score.append((qtext, pos_text))
        pair_meta.append({
            "is_positive": True,
            "query_id": qid,
            "chunk_id": pos_id,
        })

        candidates = raw_candidates_by_query.get(qid, {})
        for cid, cinfo in candidates.items():
            if cid == pos_id:
                rejected_known_positive += 1
                continue

            neg_chunk = chunk_by_id[cid]
            neg_text = format_chunk_text(neg_chunk, include_breadcrumb=True)
            neg_path = neg_chunk.get("relative_file_path", "")
            neg_bc = neg_chunk.get("breadcrumb", "")

            # Layer 1 & 2: Document proximity & Jaccard overlap
            jaccard = compute_jaccard(pos_text, neg_text)

            # Heuristic false-negative shield
            if pos_path == neg_path and (jaccard > 0.35 or (pos_bc and pos_bc == neg_bc)):
                quarantined_same_doc += 1
                quarantined_records.append({
                    "query_id": qid,
                    "positive_chunk_id": pos_id,
                    "negative_chunk_id": cid,
                    "quarantine_reason": "SAME_DOCUMENT_SECTION_OR_HIGH_OVERLAP",
                    "mining_retriever": "+".join(cinfo["retrievers"]),
                    "lexical_rank": cinfo["lexical_rank"],
                    "dense_rank": cinfo["dense_rank"],
                    "jaccard_overlap": jaccard,
                    "source_path": neg_path,
                })
                continue

            if jaccard > 0.40:
                quarantined_high_overlap += 1
                quarantined_records.append({
                    "query_id": qid,
                    "positive_chunk_id": pos_id,
                    "negative_chunk_id": cid,
                    "quarantine_reason": "HIGH_LEXICAL_OVERLAP_WITH_POSITIVE",
                    "mining_retriever": "+".join(cinfo["retrievers"]),
                    "lexical_rank": cinfo["lexical_rank"],
                    "dense_rank": cinfo["dense_rank"],
                    "jaccard_overlap": jaccard,
                    "source_path": neg_path,
                })
                continue

            # Eligible for teacher cross-encoder scoring
            pairs_to_score.append((qtext, neg_text))
            pair_meta.append({
                "is_positive": False,
                "query_id": qid,
                "chunk_id": cid,
                "retrievers": cinfo["retrievers"],
                "lexical_rank": cinfo["lexical_rank"],
                "dense_rank": cinfo["dense_rank"],
                "jaccard_overlap": jaccard,
                "source_path": neg_path,
                "pos_source_path": pos_path,
            })

    print(f"\nScoring {len(pairs_to_score)} (query, passage) pairs with teacher cross-encoder...")
    t_score_start = time.perf_counter()
    scores = teacher.predict(pairs_to_score, batch_size=64, show_progress_bar=False, convert_to_numpy=True)
    t_score_elapsed = time.perf_counter() - t_score_start
    print(f"Teacher scoring completed in {t_score_elapsed:.2f}s.")

    # Map scores back
    pos_scores: Dict[str, float] = {}
    neg_candidates_scored: Dict[str, List[Dict[str, Any]]] = {}

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

    # 7. Apply Teacher Margin & False-Negative Quarantine Criteria
    print("\nApplying teacher margin and quarantine protocol...")
    accepted_negatives: List[Dict[str, Any]] = []
    quarantined_teacher_inversion = 0
    quarantined_high_teacher_score = 0
    quarantined_ambiguous_margin = 0

    query_meta_lookup = {q["query_id"]: q for q in queries}

    for qid, cands in neg_candidates_scored.items():
        s_pos = pos_scores.get(qid, 0.0)
        q_spec = query_meta_lookup[qid]
        pos_id = q_spec["positive_chunk_id"]

        # Sort candidates by difficulty: prefer items retrieved in top lexical and dense ranks
        cands.sort(key=lambda c: (
            c["dense_rank"] if c["dense_rank"] is not None else 999,
            c["lexical_rank"] if c["lexical_rank"] is not None else 999,
        ))

        chosen_for_query = 0
        for cand in cands:
            cid = cand["chunk_id"]
            s_neg = cand["teacher_score"]
            margin = s_pos - s_neg
            cand["teacher_margin"] = margin
            cand["teacher_pos_score"] = s_pos

            # Quarantine conditions
            if margin <= 0.0:
                quarantined_teacher_inversion += 1
                quarantined_records.append({
                    "query_id": qid,
                    "positive_chunk_id": pos_id,
                    "negative_chunk_id": cid,
                    "quarantine_reason": "TEACHER_INVERSION_OR_TIE",
                    "teacher_pos_score": s_pos,
                    "teacher_score": s_neg,
                    "teacher_margin": margin,
                    "mining_retriever": "+".join(cand["retrievers"]),
                    "source_path": cand["source_path"],
                })
                continue

            if s_neg >= max_teacher_neg_score:
                quarantined_high_teacher_score += 1
                quarantined_records.append({
                    "query_id": qid,
                    "positive_chunk_id": pos_id,
                    "negative_chunk_id": cid,
                    "quarantine_reason": "HIGH_TEACHER_SCORE_POTENTIAL_TRUE_POSITIVE",
                    "teacher_pos_score": s_pos,
                    "teacher_score": s_neg,
                    "teacher_margin": margin,
                    "mining_retriever": "+".join(cand["retrievers"]),
                    "source_path": cand["source_path"],
                })
                continue

            if margin < min_teacher_margin:
                quarantined_ambiguous_margin += 1
                quarantined_records.append({
                    "query_id": qid,
                    "positive_chunk_id": pos_id,
                    "negative_chunk_id": cid,
                    "quarantine_reason": "AMBIGUOUS_TEACHER_MARGIN",
                    "teacher_pos_score": s_pos,
                    "teacher_score": s_neg,
                    "teacher_margin": margin,
                    "mining_retriever": "+".join(cand["retrievers"]),
                    "source_path": cand["source_path"],
                })
                continue

            # Accepted verified hard negative
            if s_pos >= min_teacher_pos_score:
                record = {
                    "query_id": qid,
                    "domain": q_spec["domain"],
                    "typology": q_spec.get("typology", "direct_lookup"),
                    "query_text": q_spec["query_text"],
                    "query_source_partition": "train",
                    "positive_chunk_id": pos_id,
                    "positive_source_partition": "train",
                    "negative_chunk_id": cid,
                    "negative_source_partition": "train",
                    "mining_retriever": "+".join(cand["retrievers"]),
                    "lexical_rank": cand["lexical_rank"],
                    "dense_rank": cand["dense_rank"],
                    "teacher_pos_score": s_pos,
                    "teacher_score": s_neg,
                    "teacher_margin": margin,
                    "source_path": cand["source_path"],
                    "positive_source_path": cand["pos_source_path"],
                    "verification_status": "ACCEPTED_VERIFIED_HARD_NEGATIVE",
                }

                # Validate strict partition guardrail
                validate_training_triple(record, chunk_partition_lookup=partition_lookup)

                accepted_negatives.append(record)
                chosen_for_query += 1
                if chosen_for_query >= 2:  # up to 2 high-quality verified negatives per query
                    break

    # 8. Persist Accepted Hard Negatives and Quarantine Records
    print(f"\nPersisting accepted hard negatives to {output_hard_negatives_path}...")
    Path(output_hard_negatives_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_hard_negatives_path, "w", encoding="utf-8") as f:
        for item in accepted_negatives:
            f.write(json.dumps(item) + "\n")

    print(f"Persisting quarantine records to {output_quarantine_path}...")
    Path(output_quarantine_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_quarantine_path, "w", encoding="utf-8") as f:
        for item in quarantined_records:
            f.write(json.dumps(item) + "\n")

    # 9. Compute Summary Statistics
    margins = [item["teacher_margin"] for item in accepted_negatives]
    neg_scores_accepted = [item["teacher_score"] for item in accepted_negatives]
    pos_scores_accepted = [item["teacher_pos_score"] for item in accepted_negatives]

    summary = {
        "candidates_mined": total_candidates_mined,
        "rejected_known_positives": rejected_known_positive,
        "quarantined_same_doc_proximity": quarantined_same_doc,
        "quarantined_high_lexical_overlap": quarantined_high_overlap,
        "quarantined_teacher_inversion": quarantined_teacher_inversion,
        "quarantined_high_teacher_score": quarantined_high_teacher_score,
        "quarantined_ambiguous_margin": quarantined_ambiguous_margin,
        "total_quarantined": len(quarantined_records),
        "total_accepted_hard_negatives": len(accepted_negatives),
        "unique_training_queries_covered": len({item["query_id"] for item in accepted_negatives}),
        "margin_distribution": {
            "mean": float(np.mean(margins)) if margins else 0.0,
            "median": float(np.median(margins)) if margins else 0.0,
            "min": float(np.min(margins)) if margins else 0.0,
            "max": float(np.max(margins)) if margins else 0.0,
            "std": float(np.std(margins)) if margins else 0.0,
        },
        "score_distribution": {
            "pos_score_mean": float(np.mean(pos_scores_accepted)) if pos_scores_accepted else 0.0,
            "pos_score_median": float(np.median(pos_scores_accepted)) if pos_scores_accepted else 0.0,
            "neg_score_mean": float(np.mean(neg_scores_accepted)) if neg_scores_accepted else 0.0,
            "neg_score_median": float(np.median(neg_scores_accepted)) if neg_scores_accepted else 0.0,
        },
    }

    print("\n" + "=" * 80)
    print("HARD NEGATIVE MINING v1 SUMMARY")
    print("=" * 80)
    print(f"Candidates Mined:                {summary['candidates_mined']}")
    print(f"Rejected Known Positives:        {summary['rejected_known_positives']}")
    print(f"Quarantined Total:               {summary['total_quarantined']}")
    print(f"  - Same-doc / subtopic:         {summary['quarantined_same_doc_proximity']}")
    print(f"  - High lexical overlap (>0.40):{summary['quarantined_high_lexical_overlap']}")
    print(f"  - Teacher inversion (neg >= pos):{summary['quarantined_teacher_inversion']}")
    print(f"  - High teacher score (>= 0.60):{summary['quarantined_high_teacher_score']}")
    print(f"  - Ambiguous margin (< 0.25):   {summary['quarantined_ambiguous_margin']}")
    print(f"Accepted Verified Hard Negatives:{summary['total_accepted_hard_negatives']}")
    print(f"Unique Queries Covered:          {summary['unique_training_queries_covered']}")
    print(f"Teacher Margin (Accepted):       mean={summary['margin_distribution']['mean']:.4f}, median={summary['margin_distribution']['median']:.4f}, min={summary['margin_distribution']['min']:.4f}, max={summary['margin_distribution']['max']:.4f}")
    print(f"Positive Teacher Score:          mean={summary['score_distribution']['pos_score_mean']:.4f}, median={summary['score_distribution']['pos_score_median']:.4f}")
    print(f"Negative Teacher Score:          mean={summary['score_distribution']['neg_score_mean']:.4f}, median={summary['score_distribution']['neg_score_median']:.4f}")
    print("=" * 80)

    return summary


if __name__ == "__main__":
    mine_hard_negatives()
