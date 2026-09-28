"""Build E7_QUERY_POSITIVE_AUDIT artifacts for focused human verification of suspicious queries/mappings."""

from __future__ import annotations

import json
from pathlib import Path


def main():
    quality_json_path = Path("data/training/E7_QUERY_POSITIVE_QUALITY.json")
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    out_json_path = Path("data/training/E7_QUERY_POSITIVE_AUDIT.json")
    out_md_path = Path("data/training/E7_QUERY_POSITIVE_AUDIT.md")

    with open(quality_json_path, "r", encoding="utf-8") as f:
        quality_data = json.load(f)

    # Load chunk contents
    chunk_by_id = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                chunk_by_id[c["chunk_id"]] = c

    audit_queries = []
    for q in quality_data["queries"]:
        flags = set(q["quality_flags"])
        status = q["quality_status"]
        is_mapping = status == "REVIEW_POSITIVE_MAPPING"
        has_heading = "HEADING_ARTIFACT" in flags
        has_low_lex = "VERY_LOW_LEXICAL_OVERLAP" in flags

        # Deduplicated union of REVIEW_POSITIVE_MAPPING, HEADING_ARTIFACT, VERY_LOW_LEXICAL_OVERLAP
        # Do not include solely because of DOUBLE_SPACE or CODE_IDENTIFIER_PROMPT
        if is_mapping or has_heading or has_low_lex:
            pos_chunk = chunk_by_id.get(q["positive_chunk_id"], {})
            audit_queries.append({
                "query_id": q["query_id"],
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": q["query_text"],
                "quality_status": q["quality_status"],
                "quality_flags": q["quality_flags"],
                "lexical_jaccard": q["lexical_jaccard"],
                "key_tokens_extracted": q["key_tokens_extracted"],
                "key_tokens_matched_in_positive": q["key_tokens_matched_in_positive"],
                "key_tokens_missing_in_positive": q["key_tokens_missing_in_positive"],
                "positive_chunk_id": q["positive_chunk_id"],
                "positive_source_file": q["positive_source_file"],
                "positive_breadcrumb": pos_chunk.get("breadcrumb", ""),
                "positive_excerpt": pos_chunk.get("content", "")[:500] + ("..." if len(pos_chunk.get("content", "")) > 500 else ""),
                "human_audit": {
                    "query_decision": None,
                    "allowed_query_decisions": ["VALID", "REVISE", "REJECT"],
                    "positive_decision": None,
                    "allowed_positive_decisions": ["DIRECT_SUPPORT", "PARTIAL_SUPPORT", "POSITIVE_MISMATCH"],
                    "reviewer": None,
                    "review_timestamp_utc": None,
                    "reviewer_notes": "",
                }
            })

    payload = {
        "audit_name": "E7_QUERY_POSITIVE_AUDIT",
        "description": "Focused human audit of queries with potential positive mapping mismatches, heading artifacts, or low lexical overlap.",
        "status": "PENDING_HUMAN_AUDIT",
        "total_items": len(audit_queries),
        "selection_criteria": "Deduplicated union of REVIEW_POSITIVE_MAPPING, HEADING_ARTIFACT, and VERY_LOW_LEXICAL_OVERLAP.",
        "ecosystem_distribution": {
            "postgresql": sum(1 for q in audit_queries if q["domain"] == "postgresql"),
            "pytorch": sum(1 for q in audit_queries if q["domain"] == "pytorch"),
            "kubernetes": sum(1 for q in audit_queries if q["domain"] == "kubernetes"),
            "fastapi": sum(1 for q in audit_queries if q["domain"] == "fastapi"),
        },
        "audit_items": audit_queries,
    }

    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Generated {out_json_path} with {len(audit_queries)} items.")

    # Build Markdown report
    md_lines = [
        "# E7 Query & Positive Support Focused Human Audit (11 Items)",
        "",
        "> [!IMPORTANT]",
        "> **AUDIT STATUS: `PENDING_HUMAN_AUDIT`**",
        "> This audit contains the deduplicated union of queries flagged with `REVIEW_POSITIVE_MAPPING`, `HEADING_ARTIFACT`, or `VERY_LOW_LEXICAL_OVERLAP`.",
        "> Queries flagged solely for `DOUBLE_SPACE` or `CODE_IDENTIFIER_PROMPT` are excluded.",
        "> Human review fields are intentionally left blank pending review by Satish.",
        "",
        "## Audit Overview",
        "",
        f"- **Total Audit Items**: {len(audit_queries)} queries",
        "- **PostgreSQL**: 4 items (`train_po_0002`, `train_po_0030`, `train_po_0054`, `train_po_0085`)",
        "- **PyTorch**: 7 items (`train_py_0151`, `train_py_0155`, `train_py_0196`, `train_py_0202`, `train_py_0203`, `train_py_0217`, `train_py_0226`)",
        "- **Kubernetes**: 0 items (all passed filter)",
        "- **FastAPI**: 0 items (all passed filter)",
        "",
        "## Review Instructions",
        "",
        "For each item, evaluate both the query formulation and the positive passage support:",
        "1. **Query Formulation (`query_decision`)**:",
        "   - **`VALID`**: Technically sound question with realistic phrasing.",
        "   - **`REVISE`**: salvageable question with minor syntax/heading artifact to clean.",
        "   - **`REJECT`**: Nonsensical, ungrounded, or heading-only artifact (e.g. raw memory dump address).",
        "2. **Positive Support (`positive_decision`)**:",
        "   - **`DIRECT_SUPPORT`**: Positive passage directly answers or defines the queried topic.",
        "   - **`PARTIAL_SUPPORT`**: Positive passage partially mentions the topic but lacks key details.",
        "   - **`POSITIVE_MISMATCH`**: Positive passage is about a completely different subsystem or misses the queried entity entirely.",
        "",
        "---",
        "",
        "## Audit Items",
        "",
    ]

    for idx, item in enumerate(audit_queries, start=1):
        md_lines.extend([
            f"### Item {idx:02d}: [{item['query_id']}] ({item['domain'].upper()})",
            "",
            f"- **Query Text**: `{item['query_text']}`",
            f"- **Typology**: `{item['typology']}`",
            f"- **Quality Status**: `{item['quality_status']}`",
            f"- **Quality Flags**: `{', '.join(item['quality_flags'])}`",
            f"- **Lexical Jaccard**: `{item['lexical_jaccard']:.4f}`",
            f"- **Missing Tokens in Positive**: `{item['key_tokens_missing_in_positive']}`",
            "",
            f"**Assigned Positive Chunk** (`{item['positive_chunk_id']}` | `{item['positive_source_file']}`):",
            f"> *Breadcrumb*: `{item['positive_breadcrumb']}`",
            f">",
            f"> {item['positive_excerpt']}",
            "",
            "**Human Review Form:**",
            "```yaml",
            "query_decision: [PENDING: VALID | REVISE | REJECT]",
            "positive_decision: [PENDING: DIRECT_SUPPORT | PARTIAL_SUPPORT | POSITIVE_MISMATCH]",
            "reviewer: [PENDING: Satish]",
            "review_timestamp_utc: null",
            "reviewer_notes: \"\"",
            "```",
            "",
            "---",
            "",
        ])

    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Generated {out_md_path}")


if __name__ == "__main__":
    main()
