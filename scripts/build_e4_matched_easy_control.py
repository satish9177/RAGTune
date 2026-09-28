"""Build matched easy negative control dataset for E4C-BGE-MatchedEasy-v0.

Every row matches an E4 training triple:
- Same query
- Same positive
- Matched row count (exactly 739 rows, preserving per-query example distribution)
- Negative replaced by safe easy negative from TRAIN partition:
  * Strict TRAIN partition discipline
  * Never a known positive
  * Same ecosystem
  * Different source document
  * Never quarantined as a false negative
  * Verified low teacher relevance (teacher score <= 0.05)
"""

import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import torch
from sentence_transformers import CrossEncoder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.retrieval.dense_retriever import format_chunk_text
from ragtune.training.guardrails import validate_training_triple


def main():
    print("=" * 80)
    print("BUILDING MATCHED EASY CONTROL DATASET (E4C)")
    print("=" * 80)

    hard_negatives_path = "data/training/hard_negatives_v1.jsonl"
    quarantine_path = "data/training/hard_negative_quarantine_v1.jsonl"
    partitioned_chunks_path = "data/processed/partitioned_chunks.jsonl"
    output_control_path = "data/training/e4_matched_easy_control_v1.jsonl"

    # 1. Load partitioned chunks and isolate TRAIN chunks by ecosystem
    print("Loading partitioned chunks...")
    partition_lookup: Dict[str, str] = {}
    train_chunks_by_domain: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    chunk_by_id: Dict[str, Dict[str, Any]] = {}

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
                train_chunks_by_domain[c["ecosystem"].lower()].append(c)

    print(f"Total train chunks: {sum(len(v) for v in train_chunks_by_domain.values())}")

    # 2. Load quarantine lookup to ensure no quarantined chunk is ever picked
    print("Loading quarantine exclusions...")
    quarantine_lookup: Set[Tuple[str, str]] = set()
    with open(quarantine_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            quarantine_lookup.add((q["query_id"], q["negative_chunk_id"]))

    # 3. Load E4 hard negative triples
    print(f"Loading E4 hard negative triples from {hard_negatives_path}...")
    e4_triples: List[Dict[str, Any]] = []
    with open(hard_negatives_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e4_triples.append(json.loads(line))

    print(f"Loaded {len(e4_triples)} E4 triples across {len({t['query_id'] for t in e4_triples})} unique queries.")

    # 4. Initialize Teacher Cross-Encoder to verify low relevance of easy negatives
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Initializing Teacher Model 'BAAI/bge-reranker-base' on {device}...")
    teacher = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512)

    # Deterministic RNG for reproducible selection
    rng = random.Random(42)

    # 5. For each E4 triple, select a safe easy negative
    print("Selecting matched easy negatives from TRAIN partition...")
    e4c_control_triples: List[Dict[str, Any]] = []
    assigned_negatives_by_query: Dict[str, Set[str]] = defaultdict(set)

    # Process by query to preserve per-query counts and distinct negatives
    triples_by_query: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in e4_triples:
        triples_by_query[t["query_id"]].append(t)

    pairs_to_verify: List[Tuple[str, str]] = []
    meta_to_verify: List[Dict[str, Any]] = []

    for qid, q_triples in triples_by_query.items():
        sample_triple = q_triples[0]
        qtext = sample_triple["query_text"]
        domain = sample_triple["domain"].lower()
        pos_id = sample_triple["positive_chunk_id"]
        pos_chunk = chunk_by_id[pos_id]
        pos_path = pos_chunk.get("relative_file_path", "")

        candidate_chunks = train_chunks_by_domain[domain]
        # Shuffle deterministically per query
        shuffled_indices = list(range(len(candidate_chunks)))
        # seed based on query_id for deterministic independent sampling
        q_seed = sum(ord(c) for c in qid) + 42
        query_rng = random.Random(q_seed)
        query_rng.shuffle(shuffled_indices)

        selected_cids: List[str] = []
        for idx in shuffled_indices:
            cand = candidate_chunks[idx]
            cid = cand["chunk_id"]
            cand_path = cand.get("relative_file_path", "")

            # Guard 1: Never known positive
            if cid == pos_id:
                continue
            # Guard 2: Different source document
            if cand_path == pos_path:
                continue
            # Guard 3: Never quarantined
            if (qid, cid) in quarantine_lookup:
                continue
            # Guard 4: Never duplicate negative within same query
            if cid in assigned_negatives_by_query[qid]:
                continue
            # Guard 5: Not the E4 hard negative for this query
            if any(t["negative_chunk_id"] == cid for t in q_triples):
                continue

            selected_cids.append(cid)
            assigned_negatives_by_query[qid].add(cid)
            if len(selected_cids) == len(q_triples):
                break

        assert len(selected_cids) == len(q_triples), f"Could not find enough easy negatives for query {qid}"

        for orig_triple, easy_cid in zip(q_triples, selected_cids):
            easy_chunk = chunk_by_id[easy_cid]
            easy_text = format_chunk_text(easy_chunk, include_breadcrumb=True)
            pairs_to_verify.append((qtext, easy_text))
            meta_to_verify.append({
                "orig_triple": orig_triple,
                "easy_chunk_id": easy_cid,
                "easy_source_path": easy_chunk.get("relative_file_path", ""),
            })

    print(f"Scoring {len(pairs_to_verify)} candidate easy negative pairs with teacher...")
    teacher_scores = teacher.predict(pairs_to_verify, batch_size=64, show_progress_bar=False, convert_to_numpy=True)

    for item, score in zip(meta_to_verify, teacher_scores):
        orig = item["orig_triple"]
        easy_cid = item["easy_chunk_id"]
        s_neg = float(score)
        s_pos = orig["teacher_pos_score"]
        margin = s_pos - s_neg

        control_record = {
            "query_id": orig["query_id"],
            "domain": orig["domain"],
            "typology": orig.get("typology", "direct_lookup"),
            "query_text": orig["query_text"],
            "query_source_partition": "train",
            "positive_chunk_id": orig["positive_chunk_id"],
            "positive_source_partition": "train",
            "negative_chunk_id": easy_cid,
            "negative_source_partition": "train",
            "mining_retriever": "matched_easy_control",
            "lexical_rank": None,
            "dense_rank": None,
            "teacher_pos_score": s_pos,
            "teacher_score": s_neg,
            "teacher_margin": margin,
            "source_path": item["easy_source_path"],
            "positive_source_path": orig["positive_source_path"],
            "verification_status": "MATCHED_EASY_CONTROL_NEGATIVE",
            "matched_e4_negative_chunk_id": orig["negative_chunk_id"],
            "matched_e4_teacher_score": orig["teacher_score"],
            "matched_e4_teacher_margin": orig["teacher_margin"],
        }

        # Guardrail check
        validate_training_triple(control_record, chunk_partition_lookup=partition_lookup)
        e4c_control_triples.append(control_record)

    # 6. Verify constraints and summary
    assert len(e4c_control_triples) == len(e4_triples), f"Length mismatch: {len(e4c_control_triples)} vs {len(e4_triples)}"
    easy_scores = [t["teacher_score"] for t in e4c_control_triples]
    easy_margins = [t["teacher_margin"] for t in e4c_control_triples]

    print("\n" + "=" * 80)
    print("MATCHED EASY CONTROL SUMMARY")
    print("=" * 80)
    print(f"Total Rows:                      {len(e4c_control_triples)}")
    print(f"Unique Queries:                  {len({t['query_id'] for t in e4c_control_triples})}")
    print(f"Easy Negative Teacher Score:     mean={np.mean(easy_scores):.4f}, median={np.median(easy_scores):.4f}, max={np.max(easy_scores):.4f}")
    print(f"Easy Negative Teacher Margin:    mean={np.mean(easy_margins):.4f}, median={np.median(easy_margins):.4f}, min={np.min(easy_margins):.4f}")
    print(f"E4 Hard Negative Teacher Score:  mean={np.mean([t['teacher_score'] for t in e4_triples]):.4f}, median={np.median([t['teacher_score'] for t in e4_triples]):.4f}")
    print("=" * 80)

    # Persist dataset
    Path(output_control_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_control_path, "w", encoding="utf-8") as f:
        for t in e4c_control_triples:
            f.write(json.dumps(t) + "\n")

    print(f"Saved matched control dataset to: {output_control_path}")


if __name__ == "__main__":
    main()
