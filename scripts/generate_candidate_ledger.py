"""Generate unified candidate ledger reconciling original execution vs post-hoc reconstructed accounting.

Persists: data/training/hard_negative_candidate_ledger_v1.jsonl (10,669 candidate records)
"""

import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    print("=" * 80)
    print("GENERATING HARD NEGATIVE CANDIDATE LEDGER v1")
    print("=" * 80)

    partitioned_chunks_path = "data/processed/partitioned_chunks.jsonl"
    input_queries_path = "data/training/hard_negative_audit_v0.jsonl"
    original_hn_path = "data/training/hard_negatives_v1.jsonl"
    original_quarantine_path = "data/training/hard_negative_quarantine_v1.jsonl"
    output_ledger_path = "data/training/hard_negative_candidate_ledger_v1.jsonl"

    # 1. Load original persisted artifacts
    print("Loading original persisted artifacts...")
    original_accepted_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with open(original_hn_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            original_accepted_map[(r["query_id"], r["negative_chunk_id"])] = r

    original_quarantine_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with open(original_quarantine_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            original_quarantine_map[(r["query_id"], r["negative_chunk_id"])] = r

    print(f"Loaded {len(original_accepted_map)} original accepted hard negatives.")
    print(f"Loaded {len(original_quarantine_map)} original persisted quarantine records.")

    # 2. Load train chunks and setup index
    train_chunks = []
    chunk_by_id = {}
    with open(partitioned_chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            chunk_by_id[c["chunk_id"]] = c
            if c["partition"] == "train":
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
                continue
            neg_chunk = chunk_by_id[cid]
            neg_text = format_chunk_text(neg_chunk, include_breadcrumb=True)
            neg_path = neg_chunk.get("relative_file_path", "")
            neg_bc = neg_chunk.get("breadcrumb", "")
            jaccard = compute_jaccard(pos_text, neg_text)

            if pos_path == neg_path and (jaccard > 0.35 or (pos_bc and pos_bc == neg_bc)):
                continue
            if jaccard > 0.40:
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
    neg_scores = {}
    for meta, score in zip(pair_meta, scores):
        qid = meta["query_id"]
        score_val = float(score)
        if meta["is_positive"]:
            pos_scores[qid] = score_val
        else:
            cid = meta["chunk_id"]
            neg_scores[(qid, cid)] = score_val

    # 3. Build exhaustive candidate ledger
    ledger_records: List[Dict[str, Any]] = []

    original_accounting_counts = {
        "KNOWN_POSITIVE_EXCLUSION": 0,
        "PERSISTED_QUARANTINE_RECORD": 0,
        "ACCEPTED_TRAINING_NEGATIVE": 0,
        "UNVISITED_POST_QUOTA_CANDIDATE": 0,
    }

    post_hoc_accounting_counts = {
        "KNOWN_POSITIVE_EXCLUSION": 0,
        "QUARANTINED_SAME_DOCUMENT_SUBTOPIC": 0,
        "QUARANTINED_HIGH_LEXICAL_OVERLAP": 0,
        "QUARANTINED_TEACHER_INVERSION": 0,
        "QUARANTINED_HIGH_TEACHER_SCORE": 0,
        "QUARANTINED_AMBIGUOUS_MARGIN": 0,
        "ACCEPTED_TRAINING_NEGATIVE": 0,
        "PRUNED_EXCESS_ELIGIBLE_QUOTA_EXCEEDED": 0,
        "REJECTED_LOW_POSITIVE_TEACHER_SCORE": 0,
    }

    for q in queries:
        qid = q["query_id"]
        pos_id = q["positive_chunk_id"]
        pos_chunk = chunk_by_id[pos_id]
        pos_text = format_chunk_text(pos_chunk, include_breadcrumb=True)
        pos_path = pos_chunk.get("relative_file_path", "")
        pos_bc = pos_chunk.get("breadcrumb", "")
        s_pos = pos_scores.get(qid, 0.0)

        candidates = raw_candidates_by_query.get(qid, {})
        for cid, cinfo in candidates.items():
            neg_chunk = chunk_by_id[cid]
            neg_text = format_chunk_text(neg_chunk, include_breadcrumb=True)
            neg_path = neg_chunk.get("relative_file_path", "")
            neg_bc = neg_chunk.get("breadcrumb", "")
            jaccard = compute_jaccard(pos_text, neg_text)

            s_neg = neg_scores.get((qid, cid), None)
            margin = (s_pos - s_neg) if s_neg is not None else None

            # Determine ORIGINAL execution disposition
            key = (qid, cid)
            if cid == pos_id:
                orig_disp = "KNOWN_POSITIVE_EXCLUSION"
                orig_reason = "CANDIDATE_MATCHES_KNOWN_POSITIVE"
                sel_train = False
                pers_quar = False
            elif key in original_accepted_map:
                orig_disp = "ACCEPTED_TRAINING_NEGATIVE"
                orig_reason = "PASSED_ALL_QUARANTINE_FILTERS_AND_CHOSEN_FOR_TRAINING"
                sel_train = True
                pers_quar = False
            elif key in original_quarantine_map:
                orig_disp = "PERSISTED_QUARANTINE_RECORD"
                orig_reason = original_quarantine_map[key].get("quarantine_reason", "QUARANTINED")
                sel_train = False
                pers_quar = True
            else:
                orig_disp = "UNVISITED_POST_QUOTA_CANDIDATE"
                orig_reason = "SKIPPED_DUE_TO_EARLY_LOOP_BREAK_AFTER_QUOTA_OF_2_ACCEPTED_NEGATIVES"
                sel_train = False
                pers_quar = False

            original_accounting_counts[orig_disp] += 1

            # Determine POST-HOC reconstructed disposition
            if cid == pos_id:
                post_hoc_disp = "KNOWN_POSITIVE_EXCLUSION"
                post_hoc_reason = "CANDIDATE_MATCHES_KNOWN_POSITIVE"
            elif pos_path == neg_path and (jaccard > 0.35 or (pos_bc and pos_bc == neg_bc)):
                post_hoc_disp = "QUARANTINED_SAME_DOCUMENT_SUBTOPIC"
                post_hoc_reason = "SAME_FILE_AND_HIGH_JACCARD_OR_IDENTICAL_BREADCRUMB"
            elif jaccard > 0.40:
                post_hoc_disp = "QUARANTINED_HIGH_LEXICAL_OVERLAP"
                post_hoc_reason = "JACCARD_SIMILARITY_EXCEEDS_0_40"
            elif margin is not None and margin <= 0.0:
                post_hoc_disp = "QUARANTINED_TEACHER_INVERSION"
                post_hoc_reason = "TEACHER_NEGATIVE_SCORE_GREATER_THAN_OR_EQUAL_TO_POSITIVE"
            elif s_neg is not None and s_neg >= 0.60:
                post_hoc_disp = "QUARANTINED_HIGH_TEACHER_SCORE"
                post_hoc_reason = "HIGH_TEACHER_SCORE_PROBABLE_UNANNOTATED_POSITIVE"
            elif margin is not None and margin < 0.25:
                post_hoc_disp = "QUARANTINED_AMBIGUOUS_MARGIN"
                post_hoc_reason = "AMBIGUOUS_TEACHER_MARGIN_BELOW_0_25"
            elif s_pos < 0.30:
                post_hoc_disp = "REJECTED_LOW_POSITIVE_TEACHER_SCORE"
                post_hoc_reason = "POSITIVE_TEACHER_SCORE_BELOW_0_30_THRESHOLD"
            elif sel_train:
                post_hoc_disp = "ACCEPTED_TRAINING_NEGATIVE"
                post_hoc_reason = "ACCEPTED_TEACHER_HEURISTIC_FILTERED_HARD_NEGATIVE"
            else:
                post_hoc_disp = "PRUNED_EXCESS_ELIGIBLE_QUOTA_EXCEEDED"
                post_hoc_reason = "MET_ALL_HARD_NEGATIVE_CRITERIA_BUT_EXCEEDED_PER_QUERY_QUOTA"

            post_hoc_accounting_counts[post_hoc_disp] += 1

            ledger_item = {
                "query_id": qid,
                "domain": q["domain"],
                "positive_chunk_id": pos_id,
                "candidate_chunk_id": cid,
                "retrievers": cinfo["retrievers"],
                "lexical_rank": cinfo["lexical_rank"],
                "dense_rank": cinfo["dense_rank"],
                "source_document": neg_path,
                "positive_source_document": pos_path,
                "lexical_overlap_jaccard": round(jaccard, 4),
                "positive_teacher_score": round(s_pos, 4),
                "candidate_teacher_score": round(s_neg, 4) if s_neg is not None else None,
                "teacher_margin": round(margin, 4) if margin is not None else None,
                "original_final_disposition": orig_disp,
                "original_disposition_reason": orig_reason,
                "post_hoc_reconstructed_disposition": post_hoc_disp,
                "post_hoc_disposition_reason": post_hoc_reason,
                "selected_for_training": sel_train,
                "persisted_quarantine": pers_quar,
                "reconstruction_status": "DETERMINISTICALLY_RECONSTRUCTED",
            }
            ledger_records.append(ledger_item)

    assert len(ledger_records) == total_mined == 10669

    # Write unified ledger
    Path(output_ledger_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_ledger_path, "w", encoding="utf-8") as f:
        for item in ledger_records:
            f.write(json.dumps(item) + "\n")

    print("\n" + "=" * 80)
    print("1. ORIGINAL EXECUTION ACCOUNTING (Exact File Counts)")
    print("=" * 80)
    for cat, count in original_accounting_counts.items():
        pct = (count / total_mined) * 100
        print(f"{cat:40}: {count:6d} ({pct:5.2f}%)")
    print(f"{'Total Accounted':40}: {sum(original_accounting_counts.values()):6d}")

    print("\n" + "=" * 80)
    print("2. POST-HOC RECONSTRUCTED ACCOUNTING (Exhaustive Rule Evaluation Without Early Break)")
    print("=" * 80)
    for cat, count in post_hoc_accounting_counts.items():
        pct = (count / total_mined) * 100
        print(f"{cat:40}: {count:6d} ({pct:5.2f}%)")
    print(f"{'Total Accounted':40}: {sum(post_hoc_accounting_counts.values()):6d}")
    print("=" * 80)
    print(f"Persisted ledger to: {output_ledger_path}")


if __name__ == "__main__":
    main()
