"""Build RAGTune Contrastive Training Set (v0) Grounded Strictly in the TRAIN Partition.

Ensures absolute data isolation:
- All queries, positives, and hard negatives originate exclusively from source_partition == 'train'.
- Zero chunks or queries from 'validation' or 'frozen_test' may enter training triples.
- Runtime assertions (validate_training_triple) verify 100% partition compliance.
- Hard negatives are mined via BM25 lexical confusers within 'train' and margin-filtered
  using the BAAI/bge-reranker-base teacher model.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Set, Tuple

import numpy as np
import torch
from sentence_transformers import CrossEncoder

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragtune.retrieval.dense_retriever import format_chunk_text
from ragtune.retrieval.lexical_retriever import sanitize_query_to_fts5
from ragtune.training.guardrails import (
    FrozenTestLeakageError,
    PartitionDisciplineError,
    validate_training_triple,
)


def extract_keywords_from_chunk(content: str) -> List[str]:
    """Extract salient technical terms, functions, or configurations from chunk content."""
    # Look for code identifiers or backticked terms
    code_terms = re.findall(r"`([A-Za-z0-9_.-]+)`", content)
    # Look for CamelCase or snake_case identifiers
    id_terms = re.findall(r"\b[A-Za-z][A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b", content)
    # Dotted identifiers
    dotted = re.findall(r"\b[A-Za-z0-9_]+\.[A-Za-z0-9_.]+\b", content)

    candidates = list(dict.fromkeys(code_terms + id_terms + dotted))
    # Filter short or generic
    filtered = [
        c for c in candidates
        if len(c) >= 3 and not c.isdigit() and c.lower() not in {"true", "false", "none", "null", "the", "and", "for"}
    ]
    return filtered[:6]


def generate_queries_for_chunk(
    chunk: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Synthesize structured training queries from a train chunk."""
    domain = chunk["ecosystem"]
    breadcrumb = chunk.get("breadcrumb", "").strip()
    content = chunk.get("content", "")
    keywords = extract_keywords_from_chunk(content)

    queries = []

    # Direct lookup from breadcrumb / header
    if breadcrumb and len(breadcrumb.split()) >= 2:
        clean_bc = re.sub(r"[^\w\s-]", "", breadcrumb).strip()
        queries.append({
            "typology": "direct_lookup",
            "query_text": f"What is the configuration and purpose of {clean_bc} in {domain}?",
        })

    # Keyword / identifier grounded query
    if keywords:
        primary_kw = keywords[0]
        queries.append({
            "typology": "direct_lookup",
            "query_text": f"How to use and configure {primary_kw} in {domain}?",
        })

        if len(keywords) >= 2:
            sec_kw = keywords[1]
            queries.append({
                "typology": "comparative_discrimination",
                "query_text": f"What is the difference and interaction between {primary_kw} and {sec_kw} in {domain}?",
            })

    # Troubleshooting / scenario query
    error_signals = re.findall(r"\b(error|exception|warning|fail|failed|failure|timeout|leak|oom|deadlock)\b", content.lower())
    if error_signals and keywords:
        kw = keywords[0]
        queries.append({
            "typology": "troubleshooting_scenario",
            "query_text": f"How to resolve {error_signals[0]} issues with {kw} in {domain}?",
        })

    return queries


def build_training_data(
    partitioned_path: str = "data/processed/partitioned_chunks.jsonl",
    output_triples_path: str = "data/training/retriever_train_v0.jsonl",
    output_audit_path: str = "data/training/hard_negative_audit_v0.jsonl",
    target_triples_per_domain: int = 125,
    min_teacher_margin: float = 0.15,
) -> None:
    print("=" * 75)
    print("RAGTUNE TRAINING DATA FOUNDATION GENERATION (TRAIN Partition Only)")
    print("=" * 75)

    # 1. Load partitioned chunks
    print(f"Loading partitioned chunks from {partitioned_path}...")
    chunk_partition_lookup: Dict[str, str] = {}
    train_chunks: List[Dict[str, Any]] = []
    chunks_by_domain: Dict[str, List[Dict[str, Any]]] = {
        "postgresql": [],
        "pytorch": [],
        "kubernetes": [],
        "fastapi": [],
    }

    with open(partitioned_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            cid = c["chunk_id"]
            part = c["partition"]
            chunk_partition_lookup[cid] = part

            if part == "train":
                train_chunks.append(c)
                domain = c["ecosystem"].lower()
                if domain in chunks_by_domain:
                    chunks_by_domain[domain].append(c)

    print(f"Loaded {len(train_chunks)} TRAIN chunks across {len(chunks_by_domain)} domains.")
    for d, d_chunks in chunks_by_domain.items():
        print(f"  - {d}: {len(d_chunks)} train chunks")

    # 2. Build in-memory lexical index over TRAIN partition only
    print("\nBuilding in-memory BM25 index over TRAIN chunks...")
    import sqlite3
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
    print("In-memory TRAIN lexical index ready.")

    # 3. Initialize Teacher Cross-Encoder for Margin Filtering
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nInitializing Teacher Model 'BAAI/bge-reranker-base' on {device}...")
    teacher = CrossEncoder("BAAI/bge-reranker-base", device=device, max_length=512)

    # 4. Generate candidate triples per domain
    candidate_triples: List[Dict[str, Any]] = []
    chunk_text_lookup = {
        c["chunk_id"]: format_chunk_text(c, include_breadcrumb=True)
        for c in train_chunks
    }

    print("\nSynthesizing candidate queries and mining hard negatives in TRAIN partition...")
    q_counter = 0

    for domain, d_chunks in chunks_by_domain.items():
        domain_triples = 0
        # Sort chunks by substantive token count
        eligible_chunks = [
            c for c in d_chunks
            if 80 <= c.get("token_count", 0) <= 450
        ]
        np.random.default_rng(42).shuffle(eligible_chunks)

        for chunk in eligible_chunks:
            if domain_triples >= target_triples_per_domain:
                break

            pos_id = chunk["chunk_id"]
            pos_text = chunk_text_lookup[pos_id]
            queries = generate_queries_for_chunk(chunk)

            for q_spec in queries:
                qtext = q_spec["query_text"]
                typology = q_spec["typology"]

                # Mine BM25 confusers within domain from TRAIN partition
                sanitized = sanitize_query_to_fts5(qtext)
                if not sanitized:
                    continue

                cur.execute(
                    "SELECT chunk_id, bm25(train_fts) as score FROM train_fts WHERE train_fts MATCH ? AND ecosystem = ? ORDER BY score LIMIT 10",
                    (sanitized, domain),
                )
                rows = cur.fetchall()
                if not rows:
                    continue

                # Select top retrieved chunk that is NOT the positive chunk
                neg_id = None
                for r in rows:
                    if r[0] != pos_id:
                        neg_id = r[0]
                        break

                if neg_id is None:
                    continue

                neg_text = chunk_text_lookup.get(neg_id, "")
                if not neg_text:
                    continue

                q_counter += 1
                qid = f"train_{domain[:2]}_{q_counter:04d}"

                candidate_triples.append({
                    "query_id": qid,
                    "domain": domain,
                    "typology": typology,
                    "query_text": qtext,
                    "query_source_partition": "train",
                    "positive_chunk_id": pos_id,
                    "positive_source_partition": "train",
                    "negative_chunk_id": neg_id,
                    "negative_source_partition": "train",
                    "pos_text": pos_text,
                    "neg_text": neg_text,
                })
                domain_triples += 1

    print(f"\nGenerated {len(candidate_triples)} raw candidate triples across all domains.")

    # 5. Teacher Margin Scoring and Filtering
    print("Scoring candidate triples with teacher cross-encoder...")
    pos_pairs = [(t["query_text"], t["pos_text"]) for t in candidate_triples]
    neg_pairs = [(t["query_text"], t["neg_text"]) for t in candidate_triples]

    pos_scores = teacher.predict(pos_pairs, batch_size=32, show_progress_bar=True, convert_to_numpy=True)
    neg_scores = teacher.predict(neg_pairs, batch_size=32, show_progress_bar=True, convert_to_numpy=True)

    verified_triples: List[Dict[str, Any]] = []
    audit_records: List[Dict[str, Any]] = []

    for i, t in enumerate(candidate_triples):
        s_pos = float(pos_scores[i])
        s_neg = float(neg_scores[i])
        margin = s_pos - s_neg

        audit_entry = {
            "query_id": t["query_id"],
            "domain": t["domain"],
            "typology": t["typology"],
            "query_text": t["query_text"],
            "positive_chunk_id": t["positive_chunk_id"],
            "negative_chunk_id": t["negative_chunk_id"],
            "positive_score": s_pos,
            "negative_score": s_neg,
            "teacher_margin": margin,
            "passed_margin_filter": bool(margin >= min_teacher_margin),
        }
        audit_records.append(audit_entry)

        if margin >= min_teacher_margin:
            triple_record = {
                "query_id": t["query_id"],
                "domain": t["domain"],
                "typology": t["typology"],
                "query_text": t["query_text"],
                "query_source_partition": "train",
                "positive_chunk_id": t["positive_chunk_id"],
                "positive_source_partition": "train",
                "negative_chunk_id": t["negative_chunk_id"],
                "negative_source_partition": "train",
                "teacher_margin": margin,
            }

            # Guardrail assertion
            validate_training_triple(triple_record, chunk_partition_lookup=chunk_partition_lookup)
            verified_triples.append(triple_record)

    print(f"\nFiltered to {len(verified_triples)} verified training triples (min_margin={min_teacher_margin}).")

    # 6. Persist Triples and Audit
    Path(output_triples_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_triples_path, "w", encoding="utf-8") as f:
        for vt in verified_triples:
            f.write(json.dumps(vt) + "\n")
    print(f"Saved verified training triples to: {output_triples_path}")

    with open(output_audit_path, "w", encoding="utf-8") as f:
        for ar in audit_records:
            f.write(json.dumps(ar) + "\n")
    print(f"Saved hard negative audit to: {output_audit_path}")

    # 7. Summary
    domain_counts = {}
    for vt in verified_triples:
        d = vt["domain"]
        domain_counts[d] = domain_counts.get(d, 0) + 1

    print("\n" + "=" * 75)
    print(f"TRAINING DATASET SUMMARY (N={len(verified_triples)})")
    print("Partition Discipline: 100% TRAIN Partition (0% validation, 0% frozen_test)")
    print("=" * 75)
    for d, c in domain_counts.items():
        print(f"  {d:<15}: {c} triples")
    print(f"Mean Teacher Margin: {np.mean([vt['teacher_margin'] for vt in verified_triples]):.4f}")
    print(f"Median Margin:       {np.median([vt['teacher_margin'] for vt in verified_triples]):.4f}")
    print("=" * 75)


if __name__ == "__main__":
    build_training_data()
