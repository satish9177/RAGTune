"""Mine and classify E7 reranker candidates with multi-layer false-negative protection.

Retriever foundation: E5C (BM25 + E4C Dense Hybrid Fusion RRF k=60).
Corpus: Strictly 6,414 TRAIN partition chunks.
Query universe: Exactly the 188 canonical primary queries from E7_PRIMARY_QUERY_MANIFEST.json.
Teacher: BAAI/bge-reranker-base.

Classifications per candidate:
- REJECT_KNOWN_RELEVANT
- QUARANTINE_POSSIBLE_FALSE_NEGATIVE
- REJECT_TOO_EASY
- SAFE_NEGATIVE

Outputs:
- data/training/e7_candidate_ledger.jsonl
- data/training/e7_safe_negatives.jsonl
- data/training/e7_candidate_disposition.json
- data/training/E7_NEGATIVE_AUDIT_40.json
- data/training/E7_NEGATIVE_AUDIT_40.md
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.retrieval.dense_retriever import format_chunk_text
from ragtune.retrieval.lexical_retriever import sanitize_query_to_fts5


def compute_jaccard(text1: str, text2: str) -> float:
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def truncate_text(text: str, max_chars: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "..."


def main():
    print("=" * 80)
    print("E7 RERANKER CANDIDATE MINING & FALSE-NEGATIVE PROTECTION PIPELINE")
    print("=" * 80)

    partitioned_chunks_path = "data/processed/partitioned_chunks.jsonl"
    manifest_path = "data/training/E7_PRIMARY_QUERY_MANIFEST.json"
    e4c_model_path = "data/models/e4c_bge_matchedeasy_v0/final"
    e4c_index_npy = "data/models/e4c_bge_matchedeasy_v0/index/embeddings_data_models_e4c_bge_matchedeasy_v0_final.npy"
    e4c_index_ids_json = "data/models/e4c_bge_matchedeasy_v0/index/ids_data_models_e4c_bge_matchedeasy_v0_final.json"

    out_ledger_path = "data/training/e7_candidate_ledger.jsonl"
    out_safe_neg_path = "data/training/e7_safe_negatives.jsonl"
    out_disp_path = "data/training/e7_candidate_disposition.json"
    out_audit_json_path = "data/training/E7_NEGATIVE_AUDIT_40.json"
    out_audit_md_path = "data/training/E7_NEGATIVE_AUDIT_40.md"

    # 1. Load canonical TRAIN partition chunks (6,414 chunks)
    print(f"Loading partitioned chunks from {partitioned_chunks_path}...")
    train_chunks: List[Dict[str, Any]] = []
    chunk_by_id: Dict[str, Dict[str, Any]] = {}
    partition_lookup: Dict[str, str] = {}

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

    assert len(train_chunks) == 6414, f"Expected 6414 train chunks, got {len(train_chunks)}"
    print(f"Loaded {len(train_chunks)} TRAIN chunks strictly.")

    # 2. Build in-memory BM25 index on TRAIN chunks
    print("Building in-memory BM25 index on TRAIN chunks...")
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

    # 3. Load E4C precomputed embeddings for TRAIN chunks
    print("Loading precomputed E4C dense embeddings for TRAIN partition...")
    with open(e4c_index_ids_json, "r") as f:
        all_index_ids = json.load(f)
    all_embs = np.load(e4c_index_npy)

    train_cids = [c["chunk_id"] for c in train_chunks]
    train_cid_to_pos = {cid: idx for idx, cid in enumerate(train_cids)}
    id_to_all_idx = {cid: idx for idx, cid in enumerate(all_index_ids)}

    train_embs_list = [all_embs[id_to_all_idx[cid]] for cid in train_cids]
    train_embs = np.stack(train_embs_list, axis=0)  # shape (6414, 384)

    # Normalize embeddings
    norms = np.linalg.norm(train_embs, axis=1, keepdims=True)
    train_embs = train_embs / np.maximum(norms, 1e-12)

    train_embs = train_embs.astype(np.float32)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    train_embs_tensor = torch.from_numpy(train_embs).to(device=device, dtype=torch.float32)
    print(f"TRAIN embeddings matrix ready on {device}: shape {train_embs_tensor.shape}, dtype {train_embs_tensor.dtype}")

    # 4. Load 188 Primary Queries from Manifest
    print(f"Loading primary queries from {manifest_path}...")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    queries = manifest_data["queries"]
    assert len(queries) == 188, f"Expected 188 queries, got {len(queries)}"
    print(f"Loaded {len(queries)} primary queries.")

    # 5. Encode Queries with E4C Dense Model
    print(f"Loading E4C Dense Model from {e4c_model_path} on {device}...")
    dense_model = SentenceTransformer(e4c_model_path, device=device)
    query_texts = [q["query_text"] for q in queries]
    query_embs = dense_model.encode(
        query_texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_tensor=True,
        device=device,
    )
    query_embs = query_embs.to(dtype=torch.float32)
    print(f"Queries encoded into dense representations: shape {query_embs.shape}, dtype {query_embs.dtype}")

    # 6. Retrieve Top Candidates per Query via E5C (BM25 + Dense RRF k=60)
    print("\nRetrieving candidates via BM25 + Dense + E5C Hybrid RRF (k=60)...")
    rrf_k = 60
    candidates_by_query: Dict[str, List[Dict[str, Any]]] = {}

    for i, q in enumerate(queries):
        qid = q["query_id"]
        qtext = q["query_text"]
        pos_id = q["positive_chunk_id"]
        domain = q["domain"].lower()

        # 6a. Lexical BM25 retrieval (top 25)
        bm25_ranks: Dict[str, int] = {}
        bm25_scores: Dict[str, float] = {}
        sanitized = sanitize_query_to_fts5(qtext)
        if sanitized:
            cur.execute(
                "SELECT chunk_id, bm25(train_fts) as score FROM train_fts WHERE train_fts MATCH ? AND ecosystem = ? ORDER BY score LIMIT 25",
                (sanitized, domain),
            )
            for rank, (cid, score) in enumerate(cur.fetchall(), start=1):
                bm25_ranks[cid] = rank
                bm25_scores[cid] = float(score)

        # 6b. Dense E4C retrieval (top 25 in domain)
        dense_ranks: Dict[str, int] = {}
        dense_scores: Dict[str, float] = {}
        q_emb = query_embs[i : i + 1]
        sims = torch.mm(q_emb, train_embs_tensor.t()).squeeze(0)

        # Domain filter indices
        domain_indices = [idx for idx, cid in enumerate(train_cids) if chunk_by_id[cid]["ecosystem"].lower() == domain]
        domain_sims = sims[domain_indices]
        top_k = min(25, len(domain_indices))
        top_sims, top_pos = torch.topk(domain_sims, k=top_k)

        top_sims = top_sims.cpu().tolist()
        top_pos = top_pos.cpu().tolist()

        for rank, (sim, pos) in enumerate(zip(top_sims, top_pos), start=1):
            cid = train_cids[domain_indices[pos]]
            dense_ranks[cid] = rank
            dense_scores[cid] = float(sim)

        # 6c. Reciprocal Rank Fusion (RRF k=60)
        all_candidate_ids = set(bm25_ranks.keys()) | set(dense_ranks.keys())
        fused_candidates = []

        for cid in all_candidate_ids:
            rrf_score = 0.0
            retrievers = []
            if cid in bm25_ranks:
                rrf_score += 1.0 / (rrf_k + bm25_ranks[cid])
                retrievers.append("bm25")
            if cid in dense_ranks:
                rrf_score += 1.0 / (rrf_k + dense_ranks[cid])
                retrievers.append("dense_e4c")

            fused_candidates.append({
                "chunk_id": cid,
                "rrf_score": rrf_score,
                "retrievers": retrievers,
                "lexical_rank": bm25_ranks.get(cid),
                "lexical_score": bm25_scores.get(cid),
                "dense_rank": dense_ranks.get(cid),
                "dense_score": dense_scores.get(cid),
            })

        # Sort by RRF score descending
        fused_candidates.sort(key=lambda x: x["rrf_score"], reverse=True)
        # Take top 20 candidates per query
        top_fused = fused_candidates[:20]
        for rank, cand in enumerate(top_fused, start=1):
            cand["hybrid_rank"] = rank

        candidates_by_query[qid] = top_fused

    total_candidates_mined = sum(len(cands) for cands in candidates_by_query.values())
    print(f"Mined {total_candidates_mined} total candidates across {len(queries)} queries.")

    # 7. Layered False-Negative Filtering & Teacher Cross-Encoder Scoring
    print(f"\nInitializing Teacher Cross-Encoder 'BAAI/bge-reranker-base' on {device}...")
    teacher = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512)

    # Pairs to score
    pairs_to_score: List[Tuple[str, str]] = []
    pair_meta: List[Dict[str, Any]] = []

    # Pre-screening candidates
    query_lookup = {q["query_id"]: q for q in queries}
    candidate_ledger: List[Dict[str, Any]] = []

    for q in queries:
        qid = q["query_id"]
        pos_id = q["positive_chunk_id"]
        pos_chunk = chunk_by_id[pos_id]
        pos_text = format_chunk_text(pos_chunk, include_breadcrumb=True)
        pos_path = pos_chunk.get("relative_file_path", "")
        pos_bc = pos_chunk.get("breadcrumb", "")
        qtext = q["query_text"]

        # Ensure positive pair is scored
        pairs_to_score.append((qtext, pos_text))
        pair_meta.append({"is_positive": True, "query_id": qid, "chunk_id": pos_id})

        for cand in candidates_by_query[qid]:
            cid = cand["chunk_id"]
            neg_chunk = chunk_by_id[cid]
            neg_text = format_chunk_text(neg_chunk, include_breadcrumb=True)
            neg_path = neg_chunk.get("relative_file_path", "")
            neg_bc = neg_chunk.get("breadcrumb", "")

            jaccard = compute_jaccard(pos_text, neg_text)

            ledger_entry = {
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "positive_chunk_id": pos_id,
                "candidate_chunk_id": cid,
                "mining_retriever": "+".join(cand["retrievers"]),
                "lexical_rank": cand["lexical_rank"],
                "dense_rank": cand["dense_rank"],
                "hybrid_rank": cand["hybrid_rank"],
                "rrf_score": round(cand["rrf_score"], 6),
                "lexical_overlap_jaccard": round(jaccard, 4),
                "source_document": neg_path,
                "positive_source_document": pos_path,
                "positive_teacher_score": None,
                "candidate_teacher_score": None,
                "teacher_margin": None,
                "classification": None,
                "classification_reason": None,
                "quarantine_checks": {
                    "is_not_known_positive": cid != pos_id,
                    "is_not_same_document_subtopic": not (pos_path == neg_path and (jaccard > 0.35 or (pos_bc and pos_bc == neg_bc))),
                    "is_not_high_overlap": jaccard <= 0.40,
                    "teacher_margin_positive": None,
                    "teacher_margin_ge_0_25": None,
                    "teacher_neg_below_0_60": None,
                    "teacher_pos_ge_0_30": None,
                    "teacher_neg_ge_0_02": None,
                },
            }

            # Layer 1: Known positive exclusion
            if cid == pos_id:
                ledger_entry["classification"] = "REJECT_KNOWN_RELEVANT"
                ledger_entry["classification_reason"] = "MATCHES_KNOWN_GROUND_TRUTH_POSITIVE"
                candidate_ledger.append(ledger_entry)
                continue

            # Layer 2: Same document proximity
            if pos_path == neg_path and (jaccard > 0.35 or (pos_bc and pos_bc == neg_bc)):
                ledger_entry["classification"] = "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"
                ledger_entry["classification_reason"] = "SAME_DOCUMENT_SUBTOPIC_PROXIMITY"
                candidate_ledger.append(ledger_entry)
                continue

            # Layer 3: High lexical overlap
            if jaccard > 0.40:
                ledger_entry["classification"] = "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"
                ledger_entry["classification_reason"] = "HIGH_LEXICAL_OVERLAP_WITH_POSITIVE"
                candidate_ledger.append(ledger_entry)
                continue

            # Eligible for teacher cross-encoder scoring
            pairs_to_score.append((qtext, neg_text))
            pair_meta.append({
                "is_positive": False,
                "query_id": qid,
                "chunk_id": cid,
                "ledger_idx": len(candidate_ledger),
            })
            candidate_ledger.append(ledger_entry)

    print(f"\nScoring {len(pairs_to_score)} (query, passage) pairs with BAAI/bge-reranker-base...")
    t0 = time.perf_counter()
    scores = teacher.predict(pairs_to_score, batch_size=64, show_progress_bar=False, convert_to_numpy=True)
    t_elapsed = time.perf_counter() - t0
    print(f"Teacher scoring completed in {t_elapsed:.2f}s.")

    # Map scores back
    pos_scores: Dict[str, float] = {}
    for meta, score in zip(pair_meta, scores):
        if meta["is_positive"]:
            pos_scores[meta["query_id"]] = float(score)

    for meta, score in zip(pair_meta, scores):
        if not meta["is_positive"]:
            l_idx = meta["ledger_idx"]
            qid = meta["query_id"]
            s_pos = pos_scores[qid]
            s_neg = float(score)
            margin = s_pos - s_neg

            entry = candidate_ledger[l_idx]
            entry["positive_teacher_score"] = round(s_pos, 4)
            entry["candidate_teacher_score"] = round(s_neg, 4)
            entry["teacher_margin"] = round(margin, 4)

            q_checks = entry["quarantine_checks"]
            q_checks["teacher_margin_positive"] = margin > 0.0
            q_checks["teacher_margin_ge_0_25"] = margin >= 0.25
            q_checks["teacher_neg_below_0_60"] = s_neg < 0.60
            q_checks["teacher_pos_ge_0_30"] = s_pos >= 0.30
            q_checks["teacher_neg_ge_0_02"] = s_neg >= 0.02

            # Layer 4: Teacher cross-encoder filtering
            if margin <= 0.0:
                entry["classification"] = "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"
                entry["classification_reason"] = "TEACHER_INVERSION_OR_TIE"
            elif s_neg >= 0.60:
                entry["classification"] = "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"
                entry["classification_reason"] = "HIGH_TEACHER_SCORE_PROBABLE_ANSWER"
            elif margin < 0.25:
                entry["classification"] = "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"
                entry["classification_reason"] = "AMBIGUOUS_TEACHER_MARGIN"
            elif s_pos < 0.30:
                entry["classification"] = "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"
                entry["classification_reason"] = "LOW_POSITIVE_TEACHER_CONFIDENCE"
            elif s_neg < 0.02:
                entry["classification"] = "REJECT_TOO_EASY"
                entry["classification_reason"] = "NEGLIGIBLE_TEACHER_SCORE_TRIVIAL_NEGATIVE"
            else:
                entry["classification"] = "SAFE_NEGATIVE"
                entry["classification_reason"] = "VERIFIED_E7_SAFE_HARD_NEGATIVE"

    # Fill pos_scores on previously rejected/quarantined entries for complete auditability
    for entry in candidate_ledger:
        if entry["positive_teacher_score"] is None:
            entry["positive_teacher_score"] = round(pos_scores[entry["query_id"]], 4)

    # 8. Aggregate Dispositions
    disposition_counts: Dict[str, int] = {
        "SAFE_NEGATIVE": sum(1 for e in candidate_ledger if e["classification"] == "SAFE_NEGATIVE"),
        "QUARANTINE_POSSIBLE_FALSE_NEGATIVE": sum(1 for e in candidate_ledger if e["classification"] == "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"),
        "REJECT_KNOWN_RELEVANT": sum(1 for e in candidate_ledger if e["classification"] == "REJECT_KNOWN_RELEVANT"),
        "REJECT_TOO_EASY": sum(1 for e in candidate_ledger if e["classification"] == "REJECT_TOO_EASY"),
    }
    total_ledger = len(candidate_ledger)
    assert sum(disposition_counts.values()) == total_ledger == total_candidates_mined

    print("\n" + "=" * 80)
    print("E7 CANDIDATE DISPOSITION BREAKDOWN")
    print("=" * 80)
    for cat, count in disposition_counts.items():
        pct = (count / total_ledger) * 100
        print(f"{cat:40}: {count:6d} ({pct:5.2f}%)")
    print(f"{'Total Mined Candidates':40}: {total_ledger:6d}")
    print("=" * 80)

    # Breakdown of quarantine reasons
    quarantine_reasons: Dict[str, int] = {}
    for e in candidate_ledger:
        if e["classification"] == "QUARANTINE_POSSIBLE_FALSE_NEGATIVE":
            r = e["classification_reason"]
            quarantine_reasons[r] = quarantine_reasons.get(r, 0) + 1

    print("\nQuarantine Reasons Breakdown:")
    for r, count in sorted(quarantine_reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {r:45}: {count:5d}")

    # 9. Extract Verified Safe Negatives Pool
    safe_negatives = [e for e in candidate_ledger if e["classification"] == "SAFE_NEGATIVE"]
    print(f"\nTotal SAFE_NEGATIVE candidates available: {len(safe_negatives)}")

    safe_by_eco = {}
    for e in safe_negatives:
        eco = e["domain"]
        safe_by_eco[eco] = safe_by_eco.get(eco, 0) + 1
    print(f"Safe negatives by ecosystem: {safe_by_eco}")

    # Persist candidate ledger
    print(f"Writing candidate ledger to {out_ledger_path}...")
    with open(out_ledger_path, "w", encoding="utf-8") as f:
        for item in candidate_ledger:
            f.write(json.dumps(item) + "\n")

    # Persist safe negatives
    print(f"Writing safe negatives to {out_safe_neg_path}...")
    with open(out_safe_neg_path, "w", encoding="utf-8") as f:
        for item in safe_negatives:
            f.write(json.dumps(item) + "\n")

    # Persist disposition summary
    disposition_payload = {
        "experiment": "E7_DOMAIN_RERANKER_MINING",
        "retriever_foundation": "E5C (BM25 + E4C Dense Hybrid Fusion RRF k=60)",
        "teacher_model": "BAAI/bge-reranker-base",
        "query_set": "E7_PRIMARY_QUERY_MANIFEST (188 queries)",
        "corpus_partition": "train (strictly 6,414 chunks)",
        "total_candidates_mined": total_ledger,
        "disposition_counts": disposition_counts,
        "quarantine_reasons": quarantine_reasons,
        "safe_negatives_by_ecosystem": safe_by_eco,
    }
    with open(out_disp_path, "w", encoding="utf-8") as f:
        json.dump(disposition_payload, f, indent=2)

    # 10. Generate E7 Human Audit Sample (Exactly 40 items: 10 per ecosystem)
    print("\nSampling 40 items for human audit (10 per ecosystem)...")
    audit_sample: List[Dict[str, Any]] = []

    # Sort safe negatives deterministically: domain, query_id, hybrid_rank
    safe_negatives.sort(key=lambda x: (x["domain"], x["query_id"], x["hybrid_rank"]))

    for eco in ["postgresql", "pytorch", "kubernetes", "fastapi"]:
        eco_items = [e for e in safe_negatives if e["domain"] == eco]
        assert len(eco_items) >= 10, f"Not enough safe negatives for {eco}: {len(eco_items)}"

        # Select 10 distinct queries where possible, picking top hybrid-rank safe negative
        seen_queries = set()
        selected_for_eco = []
        for it in eco_items:
            if it["query_id"] not in seen_queries:
                seen_queries.add(it["query_id"])
                selected_for_eco.append(it)
                if len(selected_for_eco) == 10:
                    break

        # If fewer than 10 distinct queries, take remaining items
        if len(selected_for_eco) < 10:
            for it in eco_items:
                if it not in selected_for_eco:
                    selected_for_eco.append(it)
                    if len(selected_for_eco) == 10:
                        break

        audit_sample.extend(selected_for_eco)

    assert len(audit_sample) == 40, f"Expected 40 audit items, got {len(audit_sample)}"

    # Build E7_NEGATIVE_AUDIT_40.json
    audit_json_items = []
    for idx, item in enumerate(audit_sample, start=1):
        q_spec = query_lookup[item["query_id"]]
        pos_chunk = chunk_by_id[item["positive_chunk_id"]]
        neg_chunk = chunk_by_id[item["candidate_chunk_id"]]

        pos_content = pos_chunk.get("content", "")
        neg_content = neg_chunk.get("content", "")

        audit_item = {
            "item_index": idx,
            "query_id": item["query_id"],
            "ecosystem": item["domain"],
            "typology": item["typology"],
            "query_text": q_spec["query_text"],
            "positive_chunk_id": item["positive_chunk_id"],
            "positive_source_path": item["positive_source_document"],
            "positive_excerpt": truncate_text(pos_content, 400),
            "hard_negative_chunk_id": item["candidate_chunk_id"],
            "hard_negative_source_path": item["source_document"],
            "hard_negative_excerpt": truncate_text(neg_content, 400),
            "mining_retriever": item["mining_retriever"],
            "lexical_rank": item["lexical_rank"],
            "dense_rank": item["dense_rank"],
            "hybrid_rank": item["hybrid_rank"],
            "rrf_score": item["rrf_score"],
            "teacher_scores": {
                "positive_score": item["positive_teacher_score"],
                "negative_score": item["candidate_teacher_score"],
                "margin": item["teacher_margin"],
            },
            "lexical_jaccard_overlap": item["lexical_overlap_jaccard"],
            "quarantine_rule_checks": item["quarantine_checks"],
            "all_quarantine_rules_passed": True,
            "human_audit": {
                "decision": None,
                "allowed_decisions": ["TRUE_NEGATIVE", "FALSE_NEGATIVE", "AMBIGUOUS"],
                "reviewer": None,
                "review_timestamp_utc": None,
                "reviewer_notes": "",
            },
        }
        audit_json_items.append(audit_item)

    audit_payload = {
        "audit_name": "E7_NEGATIVE_AUDIT_40",
        "description": "E7-specific candidate negative human audit packet sampled strictly from the verified safe-negative pool.",
        "status": "PENDING_HUMAN_AUDIT",
        "mining_foundation": "E5C (BM25 + E4C Dense Hybrid Fusion RRF k=60)",
        "teacher_model": "BAAI/bge-reranker-base",
        "total_sample_size": len(audit_json_items),
        "ecosystem_distribution": {
            "postgresql": sum(1 for a in audit_json_items if a["ecosystem"] == "postgresql"),
            "pytorch": sum(1 for a in audit_json_items if a["ecosystem"] == "pytorch"),
            "kubernetes": sum(1 for a in audit_json_items if a["ecosystem"] == "kubernetes"),
            "fastapi": sum(1 for a in audit_json_items if a["ecosystem"] == "fastapi"),
        },
        "audit_items": audit_json_items,
    }

    with open(out_audit_json_path, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2)
    print(f"Generated {out_audit_json_path}")

    # Build E7_NEGATIVE_AUDIT_40.md
    md_lines = [
        "# E7 Safe-Negative Human Verification Audit Packet (40 Items)",
        "",
        "> [!IMPORTANT]",
        "> **AUDIT STATUS: `PENDING_HUMAN_AUDIT`**",
        "> This audit packet is sampled strictly from the verified `SAFE_NEGATIVE` pool mined by the preferred Stage-1 development candidate (`E5C = BM25 + E4C Dense Hybrid RRF k=60`).",
        "> All candidates originate from the canonical `train` partition (6,414 chunks). Zero validation or test chunks are included.",
        "> **Human review fields are intentionally left blank** pending formal review by Satish.",
        "",
        "## Audit Overview",
        "",
        "- **Target Model**: E7 Cross-Encoder Domain Reranker (`BAAI/bge-reranker-base` architecture)",
        "- **Mining Retrievers**: BM25 (top-25) + E4C Matched-Easy Dense (top-25) fused via RRF ($k=60$)",
        "- **Teacher Model**: `BAAI/bge-reranker-base` (max length 512)",
        "- **Total Samples**: 40 triples (10 per ecosystem)",
        "- **Ecosystem Distribution**: PostgreSQL: 10, PyTorch: 10, Kubernetes: 10, FastAPI: 10",
        "",
        "## Review Instructions for Human Auditor",
        "",
        "For each item below, determine whether the proposed candidate negative passage is a legitimate non-relevant confuser or a false negative:",
        "1. **`TRUE_NEGATIVE`**: The passage is topically related or contains confounding terms, but does NOT answer the query.",
        "2. **`FALSE_NEGATIVE`**: The passage contains valid, answer-bearing information that directly addresses the query topic.",
        "3. **`AMBIGUOUS`**: The passage is borderline, partially answers, or contains overlapping subtopics that make penalization unsafe.",
        "",
        "---",
        "",
        "## Audit Items",
        "",
    ]

    for item in audit_json_items:
        t_scores = item["teacher_scores"]
        md_lines.extend([
            f"### Item {item['item_index']:02d}: [{item['query_id']}] ({item['ecosystem'].upper()})",
            "",
            f"- **Query**: `{item['query_text']}`",
            f"- **Typology**: `{item['typology']}`",
            f"- **Mining Fusion**: `{item['mining_retriever']}` (Hybrid Rank: #{item['hybrid_rank']}, RRF: {item['rrf_score']:.6f})",
            f"- **Teacher Scores**: $s_{{\\text{{pos}}}} = {t_scores['positive_score']:.4f}$, $s_{{\\text{{neg}}}} = {t_scores['negative_score']:.4f}$, Margin $\\Delta = {t_scores['margin']:.4f}$",
            f"- **Lexical Jaccard Overlap**: `{item['lexical_jaccard_overlap']:.4f}`",
            "",
            f"**Positive Chunk** (`{item['positive_chunk_id']}` | `{item['positive_source_path']}`):",
            f"> {item['positive_excerpt']}",
            "",
            f"**Proposed Candidate Negative** (`{item['hard_negative_chunk_id']}` | `{item['hard_negative_source_path']}`):",
            f"> {item['hard_negative_excerpt']}",
            "",
            "**Human Review Form:**",
            "```yaml",
            "decision: [PENDING: TRUE_NEGATIVE | FALSE_NEGATIVE | AMBIGUOUS]",
            "reviewer: [PENDING: Satish]",
            "review_timestamp_utc: null",
            "reviewer_notes: \"\"",
            "```",
            "",
            "---",
            "",
        ])

    with open(out_audit_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Generated {out_audit_md_path}")


if __name__ == "__main__":
    main()
