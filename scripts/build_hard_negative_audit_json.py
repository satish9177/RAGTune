"""Build machine-readable companion audit packet: data/training/HARD_NEGATIVE_AUDIT_40.json."""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def truncate_text(text: str, max_chars: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "..."


def compute_jaccard(text1: str, text2: str) -> float:
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union if union > 0 else 0.0


def main():
    hn_path = "data/training/hard_negatives_v1.jsonl"
    chunks_path = "data/processed/partitioned_chunks.jsonl"
    audit_md_path = "data/training/HARD_NEGATIVE_AUDIT_40.md"
    out_json_path = "data/training/HARD_NEGATIVE_AUDIT_40.json"

    chunk_by_id = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            chunk_by_id[c["chunk_id"]] = c

    # Parse query IDs from HARD_NEGATIVE_AUDIT_40.md to maintain identical deterministic order
    sampled_triples: List[Dict[str, Any]] = []
    sampled_qids = []
    with open(audit_md_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.search(r"#### Item \d+: \[([a-zA-Z0-9_]+)\]", line)
            if m:
                sampled_qids.append(m.group(1))

    # Load matching records from hard_negatives_v1.jsonl
    with open(hn_path, "r", encoding="utf-8") as f:
        hn_records = [json.loads(line) for line in f if line.strip()]

    hn_by_qid = {}
    for r in hn_records:
        if r["query_id"] not in hn_by_qid:
            hn_by_qid[r["query_id"]] = []
        hn_by_qid[r["query_id"]].append(r)

    audit_items = []
    for item_idx, qid in enumerate(sampled_qids, start=1):
        candidates = hn_by_qid[qid]
        # Pick the candidate matching positive chunk
        t = candidates[0]
        pos_chunk = chunk_by_id[t["positive_chunk_id"]]
        neg_chunk = chunk_by_id[t["negative_chunk_id"]]

        pos_content = pos_chunk.get("content", "")
        neg_content = neg_chunk.get("content", "")
        jaccard = compute_jaccard(pos_content, neg_content)

        quarantine_checks = {
            "distinct_chunk_id": t["positive_chunk_id"] != t["negative_chunk_id"],
            "train_partition_positive": t["positive_source_partition"] == "train",
            "train_partition_negative": t["negative_source_partition"] == "train",
            "distinct_document": t["source_path"] != t["positive_source_path"],
            "jaccard_overlap_below_threshold": jaccard <= 0.40,
            "teacher_margin_positive": t["teacher_margin"] > 0.0,
            "teacher_margin_at_least_0_25": t["teacher_margin"] >= 0.25,
            "teacher_negative_score_below_0_60": t["teacher_score"] < 0.60,
            "teacher_positive_score_at_least_0_30": t["teacher_pos_score"] >= 0.30,
        }

        audit_item = {
            "item_index": item_idx,
            "query_id": qid,
            "ecosystem": t["domain"],
            "typology": t.get("typology", "direct_lookup"),
            "query_text": t["query_text"],
            "positive_chunk_id": t["positive_chunk_id"],
            "positive_source_path": t["positive_source_path"],
            "positive_excerpt": truncate_text(pos_content, 400),
            "hard_negative_chunk_id": t["negative_chunk_id"],
            "hard_negative_source_path": t["source_path"],
            "hard_negative_excerpt": truncate_text(neg_content, 400),
            "mining_retriever": t["mining_retriever"],
            "lexical_rank": t.get("lexical_rank"),
            "dense_rank": t.get("dense_rank"),
            "teacher_scores": {
                "positive_score": t["teacher_pos_score"],
                "negative_score": t["teacher_score"],
                "margin": t["teacher_margin"],
            },
            "lexical_jaccard_overlap": round(jaccard, 4),
            "quarantine_rule_checks": quarantine_checks,
            "all_quarantine_rules_passed": all(quarantine_checks.values()),
            "human_audit": {
                "decision": None,
                "allowed_decisions": ["TRUE_NEGATIVE", "FALSE_NEGATIVE", "AMBIGUOUS"],
                "reviewer": None,
                "review_timestamp_utc": None,
                "reviewer_notes": "",
            },
        }
        audit_items.append(audit_item)

    payload = {
        "audit_name": "HARD_NEGATIVE_AUDIT_40",
        "status": "PENDING_HUMAN_AUDIT",
        "description": "Compact machine-readable companion to HARD_NEGATIVE_AUDIT_40.md for human verification of teacher/heuristic-filtered hard negatives.",
        "total_sample_size": len(audit_items),
        "ecosystem_distribution": {
            "postgresql": sum(1 for a in audit_items if a["ecosystem"] == "postgresql"),
            "pytorch": sum(1 for a in audit_items if a["ecosystem"] == "pytorch"),
            "kubernetes": sum(1 for a in audit_items if a["ecosystem"] == "kubernetes"),
            "fastapi": sum(1 for a in audit_items if a["ecosystem"] == "fastapi"),
        },
        "audit_items": audit_items,
    }

    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Generated {out_json_path} with {len(audit_items)} audit triples.")


if __name__ == "__main__":
    main()
