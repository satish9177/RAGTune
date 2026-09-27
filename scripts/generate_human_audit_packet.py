"""Generate Concise Human-Review Packet for Benchmark v0 (40 Queries).

Renders `benchmarks/review/HUMAN_AUDIT_40.md` containing:
- 17 uncertainty queries (100% of borderline candidates)
- 3 verified external queries (100% of Stack Overflow questions with exact licenses)
- 20 stratified additional queries (5 per ecosystem across typologies and provenances)

Each query includes:
- Typology, domain, role, provenance, exact license (if external), inclusion reason
- Graded relevance evidence passages with concise excerpts, chunk IDs, file paths, breadcrumbs
- Decision checkboxes: APPROVE / REVISE / REJECT
- Reviewer Notes field for Satish's human review
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def format_audit_query_markdown(
    q: Dict[str, Any],
    sample_info: Dict[str, Any],
    chunks_by_id: Dict[str, Dict[str, Any]],
    idx: int,
) -> str:
    lines = []
    qid = q["query_id"]
    eco = q["domain"]
    qtext = q["query_text"]
    meta = q.get("provenance_metadata", {})
    inc_reason = sample_info.get("inclusion_reason", "sampled")

    lines.append(f"### {idx}. `[{qid}]` {qtext}\n")
    lines.append(f"- **Ecosystem**: `{eco}` | **Typology**: `{q['typology']}` | **Role**: `{q['role']}`")
    lines.append(f"- **Provenance**: `{q['provenance_type']}` | **Inclusion Reason**: `{inc_reason}`")
    lines.append(f"- **Review Status**: `{q.get('review_status', 'AWAITING_HUMAN_REVIEW')}` | **AI Recommendation**: **`{q.get('ai_recommendation', 'APPROVE_CANDIDATE')}`**")

    # Uncertainty rationale
    if q.get("uncertainty"):
        lines.append(f"- **Uncertainty Flag**: `TRUE (Borderline / Nuanced Relevance)`")
        notes = q.get("annotation_notes", "")
        lines.append(f"  - *Audit Rationale*: Query involves multi-aspect or subtle distinctions where supporting passages provide closely related background or alternative mechanisms.")
    else:
        lines.append(f"- **Uncertainty Flag**: `False (Unambiguous Relevance)`")

    # External provenance details
    if q.get("provenance_type") == "external_derived_verified":
        lines.append("- **External Source Provenance**:")
        lines.append(f"  - *Platform*: {meta.get('platform', 'Stack Overflow')} (Post ID: `{meta.get('post_id', '')}`)")
        lines.append(f"  - *Title*: \"{meta.get('title', '')}\"")
        if meta.get("author"):
            lines.append(f"  - *Author Attribution*: `{meta['author']}`")
        if meta.get("contribution_timestamp"):
            lines.append(f"  - *Contribution Timestamp*: `{meta['contribution_timestamp']}`")
        lines.append(f"  - *Source URL*: [{meta.get('source_url', '')}]({meta.get('source_url', '')})")
        if meta.get("revision_url"):
            lines.append(f"  - *Revision History*: [{meta.get('revision_url', '')}]({meta.get('revision_url', '')})")
        lines.append(f"  - *Exact Applicable License*: **`{meta.get('license', '')}`**")
        lines.append(f"  - *Verification Date*: `{meta.get('retrieval_date', '')}`")

    lines.append("\n#### Graded Relevance Evidence Passages:")
    for r in q["relevant_chunks"]:
        cid = r["chunk_id"]
        c = chunks_by_id.get(cid)
        grade = r["grade"]
        if grade == 3:
            grade_name = "Grade 3 (Canonical Best Evidence)"
        elif grade == 2:
            grade_name = "Grade 2 (Directly Relevant Supporting)"
        else:
            grade_name = "Grade 1 (Supporting Context)"

        if c:
            excerpt = c["content"][:280].replace("\n", " ").strip()
            if len(c["content"]) > 280:
                excerpt += "..."
            lines.append(f"- **{grade_name}** — Chunk ID: `{cid[:12]}` (`{c['relative_file_path']}`, {c['token_count']} tokens)")
            lines.append(f"  - *Breadcrumb*: `{c['breadcrumb']}`")
            lines.append(f"  - *Annotation Note*: {r.get('notes', '')}")
            lines.append(f"  - *Excerpt*: > \"_{excerpt}_\"\n")
        else:
            lines.append(f"- **{grade_name}** — Chunk ID: `{cid}` (NOT FOUND IN VALIDATION PARTITION)\n")

    lines.append("#### Human Reviewer Decision (Satish):")
    lines.append("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**")
    lines.append("- **Reviewer Notes**: _____________________________________________________")
    lines.append("- **Decision Date**: ____________________\n")
    lines.append("---\n")
    return "\n".join(lines)


def generate_human_audit_packet():
    # 1. Load chunks
    chunks_by_id: Dict[str, Dict[str, Any]] = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            chunks_by_id[item["chunk_id"]] = item

    # 2. Load benchmark v0
    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    queries_by_id = {q["query_id"]: q for q in queries}

    # 3. Load sample IDs manifest
    manifest_path = Path("benchmarks/review/human_audit_sample_ids.json")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing sample manifest: {manifest_path}. Run build_benchmark_v0.py first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        sample_manifest = json.load(f)

    sample_details = {d["query_id"]: d for d in sample_manifest["sample_details"]}
    sample_qids = sample_manifest["sample_query_ids"]

    # Order queries by ecosystem: postgresql, pytorch, kubernetes, fastapi
    eco_order = {"postgresql": 0, "pytorch": 1, "kubernetes": 2, "fastapi": 3}
    ordered_sample_queries = sorted(
        [queries_by_id[qid] for qid in sample_qids if qid in queries_by_id],
        key=lambda q: (eco_order.get(q["domain"], 99), q["query_id"]),
    )

    # Build markdown packet
    doc_lines = [
        "# RAGTune Benchmark v0: 40-Query Human Audit Packet\n",
        f"**Target**: Deterministic 40-Query Human Review Sample of Benchmark v0\n",
        f"**Auditor**: Satish (Human Reviewer) | **Current State**: `AWAITING_HUMAN_REVIEW`\n",
        f"**Random Seed**: 42 | **Sampling Strategy**: `deterministic_stratified_v1`\n\n",
        "> [!IMPORTANT]",
        "> **Benchmark v0 Freeze Contract**: Benchmark v0 will be officially frozen only after Satish completes human review of this 40-query audit sample.",
        "> Queries marked `AWAITING_HUMAN_REVIEW` remain open until human decision checkboxes and notes are resolved. No human decisions are simulated by the AI assistant.\n\n",
        "## Audit Sample Composition\n",
        "| Category | Count | Description |",
        "| :--- | :--- | :--- |",
        f"| **Uncertainty Flagged** | {sample_manifest['composition']['uncertain_queries']} | 100% of queries identified with borderline or multi-aspect relevance |",
        f"| **Verified External Queries** | {sample_manifest['composition']['external_verified_queries']} | 100% of Stack Overflow questions with exact revision/license tracking |",
        f"| **Stratified Additional Sample** | {sample_manifest['composition']['stratified_additional_queries']} | Deterministically sampled across all 4 ecosystems and typologies (seed=42) |",
        f"| **Total Audit Sample** | **{len(ordered_sample_queries)}** | **Full representative sample (28.6% of 140 benchmark queries)** |\n\n",
        "### Ecosystem Distribution in Audit Sample\n",
        f"- **PostgreSQL**: {sample_manifest['domain_counts']['postgresql']} queries (5 uncertain + 1 external + 5 stratified)",
        f"- **PyTorch**: {sample_manifest['domain_counts']['pytorch']} queries (4 uncertain + 1 external + 5 stratified)",
        f"- **Kubernetes**: {sample_manifest['domain_counts']['kubernetes']} queries (5 uncertain + 0 external + 5 stratified)",
        f"- **FastAPI**: {sample_manifest['domain_counts']['fastapi']} queries (3 uncertain + 1 external + 5 stratified)\n\n",
        "### Typology Distribution in Audit Sample\n",
        f"- **Direct Lookup**: {sample_manifest['typology_counts']['direct_lookup']} queries",
        f"- **Comparative Discrimination**: {sample_manifest['typology_counts']['comparative_discrimination']} queries",
        f"- **Troubleshooting Scenario**: {sample_manifest['typology_counts']['troubleshooting_scenario']} queries\n\n",
        "---\n\n",
        "## Summary Table of 40 Audit Queries\n\n",
        "| # | Query ID | Ecosystem | Typology | Provenance | Reason | AI Rec |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for idx, q in enumerate(ordered_sample_queries, start=1):
        s_info = sample_details.get(q["query_id"], {})
        reason = s_info.get("inclusion_reason", "")
        doc_lines.append(
            f"| {idx} | `{q['query_id']}` | `{q['domain']}` | `{q['typology']}` | `{q['provenance_type']}` | `{reason}` | `{q.get('ai_recommendation', 'APPROVE_CANDIDATE')}` |"
        )

    doc_lines.append("\n---\n\n")

    # Grouped review sections
    by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for q in ordered_sample_queries:
        by_domain.setdefault(q["domain"], []).append(q)

    global_idx = 1
    for domain in ["postgresql", "pytorch", "kubernetes", "fastapi"]:
        d_queries = by_domain.get(domain, [])
        doc_lines.append(f"## {domain.upper()} AUDIT SAMPLE ({len(d_queries)} Queries)\n\n")
        for q in d_queries:
            s_info = sample_details.get(q["query_id"], {})
            doc_lines.append(format_audit_query_markdown(q, s_info, chunks_by_id, global_idx))
            global_idx += 1

    out_path = Path("benchmarks/review/HUMAN_AUDIT_40.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(doc_lines))

    print(f"Generated human audit packet with {len(ordered_sample_queries)} queries: {out_path}")
    return out_path


if __name__ == "__main__":
    generate_human_audit_packet()
