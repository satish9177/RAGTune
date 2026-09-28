"""Validate structural query and positive mapping quality for E7 Primary Query Set (188 queries).

Produces:
- data/training/E7_PRIMARY_QUERY_MANIFEST.json
- data/training/E7_QUERY_POSITIVE_QUALITY.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List


def compute_jaccard(text1: str, text2: str) -> float:
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


def main():
    queries_path = Path("data/training/retriever_train_v0.jsonl")
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    manifest_path = Path("data/training/E7_PRIMARY_QUERY_MANIFEST.json")
    quality_path = Path("data/training/E7_QUERY_POSITIVE_QUALITY.json")

    # Load 188 canonical train queries
    with open(queries_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f if line.strip()]

    assert len(queries) == 188, f"Expected 188 queries, got {len(queries)}"

    # Load chunks lookup
    chunks = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunks[c["chunk_id"]] = c

    # 1. Generate E7_PRIMARY_QUERY_MANIFEST.json
    manifest_queries = []
    for q in queries:
        pos_chunk = chunks[q["positive_chunk_id"]]
        manifest_queries.append({
            "query_id": q["query_id"],
            "domain": q["domain"],
            "typology": q.get("typology", "direct_lookup"),
            "query_text": q["query_text"],
            "query_source_partition": q.get("query_source_partition", "train"),
            "positive_chunk_id": q["positive_chunk_id"],
            "positive_source_partition": q.get("positive_source_partition", "train"),
            "positive_file_path": pos_chunk.get("relative_file_path"),
            "positive_breadcrumb": pos_chunk.get("breadcrumb"),
        })

    manifest_data = {
        "manifest_name": "E7_PRIMARY_QUERY_MANIFEST",
        "description": "Canonical 188-query primary population locked for E7 domain reranker mining and training.",
        "target_stage": "Stage-2 Cross-Encoder Domain Reranker (E7)",
        "retriever_foundation": "E5C (BM25 + E4C Matched-Easy Dense Hybrid RRF k=60)",
        "total_queries": len(manifest_queries),
        "ecosystem_distribution": {
            "pytorch": sum(1 for q in manifest_queries if q["domain"] == "pytorch"),
            "postgresql": sum(1 for q in manifest_queries if q["domain"] == "postgresql"),
            "kubernetes": sum(1 for q in manifest_queries if q["domain"] == "kubernetes"),
            "fastapi": sum(1 for q in manifest_queries if q["domain"] == "fastapi"),
        },
        "queries": manifest_queries,
    }

    manifest_json_str = json.dumps(manifest_data, indent=2, sort_keys=True)
    manifest_sha = hashlib.sha256(manifest_json_str.encode("utf-8")).hexdigest()
    manifest_data["manifest_sha256"] = manifest_sha

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, sort_keys=True)

    # Re-compute exact file hash of the final written artifact
    with open(manifest_path, "rb") as f:
        exact_file_sha = hashlib.sha256(f.read()).hexdigest()

    print(f"Generated {manifest_path} with {len(manifest_queries)} queries (SHA-256: {exact_file_sha})")

    # 2. Perform Structural Quality and Positive Mapping Validation
    stop_words = {
        "what", "is", "the", "how", "to", "use", "and", "configure", "in", "of",
        "difference", "interaction", "between", "resolve", "issues", "with", "for",
        "postgresql", "pytorch", "kubernetes", "fastapi", "a", "an", "purpose", "configuration"
    }

    evaluated_queries = []
    status_counts = {"CLEAN": 0, "REVIEW_QUERY": 0, "REVIEW_POSITIVE_MAPPING": 0}
    flag_frequency: Dict[str, int] = {}

    for q in manifest_queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        pos_id = q["positive_chunk_id"]
        pos = chunks[pos_id]
        pcontent = pos.get("content", "")
        pcontent_lower = pcontent.lower()

        flags = []

        # Check positive partition integrity
        if pos.get("partition") != "train":
            flags.append("NON_TRAIN_POSITIVE_PARTITION")

        # Substantive entity extraction
        tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_]{3,}\b", qtext) if w.lower() not in stop_words]
        matched_tokens = [t for t in tokens if t in pcontent_lower]
        missing_tokens = [t for t in tokens if t not in pcontent_lower]

        jaccard = compute_jaccard(qtext, pcontent)

        # Mapping checks
        if len(tokens) > 0 and len(matched_tokens) == 0:
            flags.append("NO_QUERY_ENTITIES_IN_POSITIVE")
        elif jaccard < 0.025:
            flags.append("VERY_LOW_LEXICAL_OVERLAP")

        # Query syntax & artifact checks
        if "  " in qtext:
            flags.append("DOUBLE_SPACE_IN_QUERY")
        if re.search(r"REL_16_STABLE|CUDA semantics|Troubleshooting  Minifying|Features -|b7f064c0", qtext):
            flags.append("HEADING_ARTIFACT")
        if re.search(r"\b(missing_ok|locked_row|do_db_maintenance|replace_all_batch_norm_modules_|add_scalar|minifier_launcher|quantize_per_tensor|controller_utils|deprecatedVersion|user_indict|github_sponsors|three_months_experts|maximum_length|six_months_experts)\b", qtext):
            flags.append("CODE_IDENTIFIER_PROMPT")

        # Determine status
        if "NON_TRAIN_POSITIVE_PARTITION" in flags or "NO_QUERY_ENTITIES_IN_POSITIVE" in flags:
            status = "REVIEW_POSITIVE_MAPPING"
        elif flags:
            status = "REVIEW_QUERY"
        else:
            status = "CLEAN"

        status_counts[status] += 1
        for fl in flags:
            flag_frequency[fl] = flag_frequency.get(fl, 0) + 1

        evaluated_queries.append({
            "query_id": qid,
            "domain": q["domain"],
            "typology": q["typology"],
            "query_text": qtext,
            "positive_chunk_id": pos_id,
            "positive_source_file": q["positive_file_path"],
            "quality_status": status,
            "quality_flags": flags,
            "lexical_jaccard": round(jaccard, 4),
            "key_tokens_extracted": tokens,
            "key_tokens_matched_in_positive": matched_tokens,
            "key_tokens_missing_in_positive": missing_tokens,
        })

    quality_report = {
        "report_name": "E7_QUERY_POSITIVE_QUALITY",
        "description": "Structural quality and positive mapping validation over canonical 188 E7 primary queries.",
        "target_stage": "Stage-2 Cross-Encoder Domain Reranker (E7)",
        "total_queries_evaluated": len(evaluated_queries),
        "status_distribution": status_counts,
        "flag_frequency": flag_frequency,
        "queries": evaluated_queries,
    }

    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, sort_keys=True)

    print(f"Generated {quality_path}")
    print(f"Status distribution: {status_counts}")
    print(f"Flag frequencies: {flag_frequency}")


if __name__ == "__main__":
    main()
