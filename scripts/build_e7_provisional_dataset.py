"""Build provisional E7 cross-encoder reranker training dataset.

Applies strong provisional hardness filtering and semantic risk guards to the
652 SAFE_NEGATIVE_V2 candidates.
Excludes queries pending explicit human review in E7_PROVISIONAL_QUERY_EXCLUSIONS.json.
Caps training negatives at max 3 per query, prioritizing hybrid confusers.

Outputs:
- data/training/e7_provisional_negative_ledger.jsonl
- data/training/e7_reranker_train_provisional_v1.jsonl
- data/training/e7_provisional_dataset_disposition.json
"""

from __future__ import annotations

from collections import defaultdict
import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ragtune.retrieval.dense_retriever import format_chunk_text


def compute_file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    root = Path(__file__).resolve().parent.parent
    exclusions_path = root / "data" / "training" / "E7_PROVISIONAL_QUERY_EXCLUSIONS.json"
    manifest_path = root / "data" / "training" / "E7_PRIMARY_QUERY_MANIFEST.json"
    chunks_path = root / "data" / "processed" / "partitioned_chunks.jsonl"
    safe_v2_path = root / "data" / "training" / "e7_safe_negatives_v2.jsonl"

    out_ledger_path = root / "data" / "training" / "e7_provisional_negative_ledger.jsonl"
    out_train_path = root / "data" / "training" / "e7_reranker_train_provisional_v1.jsonl"
    out_disp_path = root / "data" / "training" / "e7_provisional_dataset_disposition.json"

    print("=" * 80)
    print("BUILDING E7 PROVISIONAL TRAINING DATASET")
    print("=" * 80)

    # 1. Load exclusions
    with open(exclusions_path, "r", encoding="utf-8") as f:
        excl_data = json.load(f)
    excluded_qids = set(excl_data["excluded_query_ids"])
    print(f"Loaded {len(excluded_qids)} excluded queries from {exclusions_path.name}.")

    # 2. Load primary query manifest
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    query_lookup = {q["query_id"]: q for q in manifest["queries"]}
    print(f"Loaded {len(query_lookup)} train queries from {manifest_path.name}.")

    # 3. Load train chunks
    print("Loading train partition chunk contents...")
    train_chunks: Dict[str, Dict[str, Any]] = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            if c["partition"] == "train":
                train_chunks[c["chunk_id"]] = c
    print(f"Loaded {len(train_chunks)} train partition chunks.")

    # 4. Load safe_negatives_v2 (652 items)
    safe_v2_items = []
    with open(safe_v2_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                safe_v2_items.append(json.loads(line))
    print(f"Loaded {len(safe_v2_items)} candidate rows from {safe_v2_path.name}.")

    # 5. Classify every candidate
    provisional_ledger: List[Dict[str, Any]] = []
    disposition_counts = {
        "PROVISIONAL_TRAINABLE_NEGATIVE": 0,
        "QUARANTINE_SEMANTIC_RISK": 0,
        "REJECT_TRIVIAL_NOT_HARD": 0,
        "EXCLUDED_QUERY_PENDING_REVIEW": 0,
    }

    trainable_by_query = defaultdict(list)

    for item in safe_v2_items:
        qid = item["query_id"]
        s_neg = item.get("candidate_teacher_score") or 0.0
        margin = item.get("teacher_margin") or 0.0

        hyb_rank = item.get("hybrid_rank")
        dense_rank = item.get("dense_rank")
        lex_rank = item.get("lexical_rank")

        has_top10 = (
            (hyb_rank is not None and hyb_rank <= 10)
            or (dense_rank is not None and dense_rank <= 10)
            or (lex_rank is not None and lex_rank <= 10)
        )

        entry = dict(item)

        if qid in excluded_qids:
            disp = "EXCLUDED_QUERY_PENDING_REVIEW"
            reason = "QUERY_FLAGGED_IN_QUERY_POSITIVE_AUDIT"
        elif s_neg >= 0.50:
            disp = "QUARANTINE_SEMANTIC_RISK"
            reason = "EXCESSIVE_TEACHER_SCORE_POTENTIAL_FALSE_NEGATIVE"
        elif margin < 0.30:
            disp = "QUARANTINE_SEMANTIC_RISK"
            reason = "INSUFFICIENT_TEACHER_MARGIN_BELOW_0_30"
        elif s_neg < 0.025:
            disp = "REJECT_TRIVIAL_NOT_HARD"
            reason = "TEACHER_SCORE_BELOW_HARDNESS_THRESHOLD_0_025"
        elif not has_top10:
            disp = "REJECT_TRIVIAL_NOT_HARD"
            reason = "NOT_RETRIEVED_IN_TOP10_BY_ANY_RETRIEVER"
        else:
            disp = "PROVISIONAL_TRAINABLE_NEGATIVE"
            reason = "VERIFIED_HARD_CONFUSER_SAFE_NEGATIVE"

        entry["provisional_classification"] = disp
        entry["provisional_classification_reason"] = reason
        disposition_counts[disp] += 1
        provisional_ledger.append(entry)

        if disp == "PROVISIONAL_TRAINABLE_NEGATIVE":
            # Priority scoring: Tier 1 (hybrid), Tier 2 (dense), Tier 3 (lexical)
            if hyb_rank is not None and hyb_rank <= 10:
                tier = 1
                subrank = hyb_rank
            elif dense_rank is not None and dense_rank <= 10:
                tier = 2
                subrank = dense_rank
            else:
                tier = 3
                subrank = lex_rank or 999

            trainable_by_query[qid].append((tier, subrank, -s_neg, entry))

    # Write out ledger
    with open(out_ledger_path, "w", encoding="utf-8") as f:
        for entry in provisional_ledger:
            f.write(json.dumps(entry) + "\n")
    print(f"Persisted full ledger to {out_ledger_path.name}.")

    # 6. Select max 3 negatives per query
    selected_training_records: List[Dict[str, Any]] = []
    unique_eligible_queries = sorted(list(trainable_by_query.keys()))

    print(f"\nUnique queries with trainable negatives: {len(unique_eligible_queries)}")
    if len(unique_eligible_queries) < 75:
        raise RuntimeError(
            f"Predeclared guardrail failed: eligible query count {len(unique_eligible_queries)} < 75 minimum requirement!"
        )

    for qid in unique_eligible_queries:
        cands = trainable_by_query[qid]
        cands.sort(key=lambda x: (x[0], x[1], x[2]))
        top_cands = [item[3] for item in cands[:3]]

        q_spec = query_lookup[qid]
        q_text = q_spec["query_text"]
        pos_cid = q_spec["positive_chunk_id"]

        assert pos_cid in train_chunks, f"Positive chunk {pos_cid} missing from train partition!"
        pos_chunk = train_chunks[pos_cid]
        pos_text = format_chunk_text(pos_chunk, include_breadcrumb=True)

        for rank_idx, cand in enumerate(top_cands, start=1):
            neg_cid = cand["candidate_chunk_id"]
            assert neg_cid in train_chunks, f"Negative chunk {neg_cid} missing from train partition!"
            neg_chunk = train_chunks[neg_cid]
            neg_text = format_chunk_text(neg_chunk, include_breadcrumb=True)

            rec = {
                "query_id": qid,
                "domain": cand["domain"],
                "typology": cand["typology"],
                "query_text": q_text,
                "positive_chunk_id": pos_cid,
                "positive_source_document": pos_chunk.get("source_file", ""),
                "positive_text": pos_text,
                "negative_chunk_id": neg_cid,
                "negative_source_document": neg_chunk.get("source_file", ""),
                "negative_text": neg_text,
                "mining_retriever": cand.get("mining_retriever", "hybrid"),
                "hybrid_rank": cand.get("hybrid_rank"),
                "dense_rank": cand.get("dense_rank"),
                "lexical_rank": cand.get("lexical_rank"),
                "candidate_teacher_score": cand.get("candidate_teacher_score"),
                "teacher_margin": cand.get("teacher_margin"),
                "query_negative_rank": rank_idx,
            }
            selected_training_records.append(rec)

    # Assertions
    assert len(selected_training_records) > 0, "No training records selected!"
    assert len(unique_eligible_queries) >= 75, "Fewer than 75 unique training queries!"
    for r in selected_training_records:
        assert r["query_id"] not in excluded_qids, f"Excluded query {r['query_id']} leaked into training data!"
        assert r["positive_chunk_id"] != r["negative_chunk_id"], "Positive matches negative!"
        assert train_chunks[r["positive_chunk_id"]]["partition"] == "train"
        assert train_chunks[r["negative_chunk_id"]]["partition"] == "train"

    # Persist training data
    with open(out_train_path, "w", encoding="utf-8") as f:
        for r in selected_training_records:
            f.write(json.dumps(r) + "\n")
    print(f"Persisted {len(selected_training_records)} training records to {out_train_path.name}.")

    domain_counts = defaultdict(int)
    for r in selected_training_records:
        domain_counts[r["domain"]] += 1

    disposition_payload = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_safe_v2_candidates": len(safe_v2_items),
        "disposition_counts": disposition_counts,
        "unique_queries_with_trainable_negatives": len(unique_eligible_queries),
        "total_training_records": len(selected_training_records),
        "domain_distribution": dict(domain_counts),
        "training_file": str(out_train_path.relative_to(root)),
        "training_file_sha256": compute_file_sha256(out_train_path),
        "ledger_file": str(out_ledger_path.relative_to(root)),
        "ledger_file_sha256": compute_file_sha256(out_ledger_path),
    }

    with open(out_disp_path, "w", encoding="utf-8") as f:
        json.dump(disposition_payload, f, indent=2)
    print(f"Persisted disposition summary to {out_disp_path.name}.")

    print("\nDisposition Summary:")
    for k, v in disposition_counts.items():
        print(f"  {k:35}: {v:5d} ({v/len(safe_v2_items)*100:5.2f}%)")
    print(f"\nFinal Selected Training Records: {len(selected_training_records)}")
    print(f"Unique Queries: {len(unique_eligible_queries)}")
    print(f"By Domain: {dict(domain_counts)}")


if __name__ == "__main__":
    main()
