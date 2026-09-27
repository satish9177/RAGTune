"""Audit Benchmark v0 Quality and Generate Human-Review Packets.

Performs:
1. Anti-parroting audit (lexical overlap against evidence).
2. Near-duplicate query detection (cross-query Jaccard pairwise comparison).
3. Repeated question stem analysis.
4. Canonical chunk reuse frequency.
5. Generates benchmarks/benchmark_v0_quality_audit.json.
6. Generates formatted review packets:
   - benchmarks/review/benchmark_v0_review.md
   - benchmarks/review/{domain}_review.md (4 sub-packets)
   - benchmarks/review/benchmark_v0_review.csv
   - benchmarks/review/benchmark_v0_review.json
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from scripts.generate_human_audit_packet import generate_human_audit_packet


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", text) if len(t) > 0]


def jaccard(s1: str, s2: str) -> float:
    t1 = set(tokenize(s1))
    t2 = set(tokenize(s2))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


def main():
    print("=" * 70)
    print("AUDITING BENCHMARK V0 QUALITY & GENERATING HUMAN-REVIEW PACKETS")
    print("=" * 70)

    # Load chunks
    chunks_by_id: Dict[str, Dict[str, Any]] = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            chunks_by_id[item["chunk_id"]] = item

    # Load benchmark v0
    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    print(f"Loaded {len(queries)} queries and {len(chunks_by_id)} corpus chunks.")

    # 1. Quality Audit
    # A. Pairwise query similarity (detecting near-duplicate queries)
    high_overlap_query_pairs = []
    n = len(queries)
    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard(queries[i]["query_text"], queries[j]["query_text"])
            if sim >= 0.60:
                high_overlap_query_pairs.append({
                    "query_id_1": queries[i]["query_id"],
                    "query_id_2": queries[j]["query_id"],
                    "similarity": round(sim, 4),
                    "q1": queries[i]["query_text"],
                    "q2": queries[j]["query_text"],
                })

    # B. Lexical overlap against canonical evidence
    evidence_overlaps = []
    for q in queries:
        c3_id = next(r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3)
        c3 = chunks_by_id[c3_id]
        sim = jaccard(q["query_text"], c3["content"])
        evidence_overlaps.append({
            "query_id": q["query_id"],
            "domain": q["domain"],
            "provenance_type": q["provenance_type"],
            "jaccard_vs_canonical": round(sim, 4),
        })

    # C. Repeated question stems
    stems: Dict[str, int] = {}
    for q in queries:
        words = tokenize(q["query_text"])
        stem = " ".join(words[:3]) if len(words) >= 3 else ""
        if stem:
            stems[stem] = stems.get(stem, 0) + 1

    common_stems = {k: v for k, v in stems.items() if v >= 3}

    # D. Canonical evidence reuse
    c3_usage: Dict[str, List[str]] = {}
    for q in queries:
        c3_id = next(r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3)
        c3_usage.setdefault(c3_id, []).append(q["query_id"])

    overused_chunks = {cid: qids for cid, qids in c3_usage.items() if len(qids) > 2}

    # Quality Audit Summary
    quality_audit = {
        "benchmark_id": "benchmark_v0",
        "total_queries_audited": len(queries),
        "near_duplicate_query_pairs_ge_0_60": high_overlap_query_pairs,
        "anti_parroting_summary": {
            "mean_jaccard_vs_evidence": round(float(sum(x["jaccard_vs_canonical"] for x in evidence_overlaps) / len(evidence_overlaps)), 4),
            "max_jaccard_vs_evidence": round(max(x["jaccard_vs_canonical"] for x in evidence_overlaps), 4),
            "pairs_ge_0_40": [x for x in evidence_overlaps if x["jaccard_vs_canonical"] >= 0.40],
        },
        "repeated_question_stems": common_stems,
        "overused_canonical_evidence_chunks": overused_chunks,
        "relevance_positive_distribution": {
            "queries_with_1_positive": sum(1 for q in queries if len(q["relevant_chunks"]) == 1),
            "queries_with_2_positives": sum(1 for q in queries if len(q["relevant_chunks"]) == 2),
            "queries_with_3_or_more_positives": sum(1 for q in queries if len(q["relevant_chunks"]) >= 3),
        },
        "uncertainty_audit": {
            "total_uncertain": sum(1 for q in queries if q["uncertainty"]),
            "uncertain_queries": [
                {"query_id": q["query_id"], "domain": q["domain"], "query_text": q["query_text"]}
                for q in queries if q["uncertainty"]
            ],
        },
        "review_status_summary": {
            "AWAITING_HUMAN_REVIEW": sum(1 for q in queries if q.get("review_status") == "AWAITING_HUMAN_REVIEW"),
            "AI_SOURCE_VERIFIED": sum(1 for q in queries if q.get("review_status") == "AI_SOURCE_VERIFIED"),
            "HUMAN_APPROVED": sum(1 for q in queries if q.get("review_status") == "HUMAN_APPROVED"),
            "HUMAN_REVISED": sum(1 for q in queries if q.get("review_status") == "HUMAN_REVISED"),
            "HUMAN_REJECTED": sum(1 for q in queries if q.get("review_status") == "HUMAN_REJECTED"),
            "UNREVIEWED": sum(1 for q in queries if q.get("review_status") == "UNREVIEWED"),
            "ai_recommendations": {
                "APPROVE_CANDIDATE": sum(1 for q in queries if q.get("ai_recommendation") == "APPROVE_CANDIDATE"),
                "REVISE_CANDIDATE": sum(1 for q in queries if q.get("ai_recommendation") == "REVISE_CANDIDATE"),
                "REJECT_CANDIDATE": sum(1 for q in queries if q.get("ai_recommendation") == "REJECT_CANDIDATE"),
            }
        },
        "freeze_rule": "Benchmark v0 will be officially frozen only after Satish completes human review of the 40-query sample in HUMAN_AUDIT_40.md."
    }

    audit_path = Path("benchmarks/benchmark_v0_quality_audit.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(quality_audit, f, indent=2)
    print(f"Saved quality audit report to: {audit_path}")

    # 2. Generate Human Review Packets
    review_dir = Path("benchmarks/review")
    review_dir.mkdir(parents=True, exist_ok=True)

    def format_query_markdown(q: Dict[str, Any], idx: int) -> str:
        lines = []
        qid = q["query_id"]
        eco = q["domain"]
        qtext = q["query_text"]
        lines.append(f"### {idx}. `[{qid}]` {qtext}\n")
        lines.append(f"- **Ecosystem**: `{eco}` | **Typology**: `{q['typology']}` | **Role**: `{q['role']}`")
        lines.append(f"- **Provenance**: `{q['provenance_type']}`")
        if q["provenance_metadata"]:
            lines.append(f"  - *Metadata*: `{json.dumps(q['provenance_metadata'])}`")
        lines.append(f"- **Uncertainty Flag**: `{'TRUE (Borderline / Nuanced)' if q['uncertainty'] else 'False (Unambiguous)'}`")
        lines.append(f"- **AI Quality Recommendation**: **`{q.get('ai_recommendation', 'APPROVE_CANDIDATE')}`**\n")

        lines.append("#### Graded Relevance Evidence Passages:")
        for r in q["relevant_chunks"]:
            cid = r["chunk_id"]
            c = chunks_by_id.get(cid)
            grade = r["grade"]
            grade_name = "Grade 3 (Canonical Best Evidence)" if grade == 3 else "Grade 2 (Directly Relevant)" if grade == 2 else "Grade 1 (Supporting Context)"
            if c:
                excerpt = c["content"][:300].replace("\n", " ").strip() + "..."
                lines.append(f"- **{grade_name}** — Chunk ID: `{cid[:12]}` (`{c['relative_file_path']}`, {c['token_count']} tokens)")
                lines.append(f"  - *Breadcrumb*: `{c['breadcrumb']}`")
                lines.append(f"  - *Annotation Note*: {r.get('notes', '')}")
                lines.append(f"  - *Excerpt*: > \"_{excerpt}_\"\n")
            else:
                lines.append(f"- **{grade_name}** — Chunk ID: `{cid}` (NOT FOUND)\n")

        lines.append("#### Human Reviewer Decision (Satish):")
        lines.append("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**")
        lines.append("- **Reviewer Notes**: _____________________________________________________\n")
        lines.append("---\n")
        return "\n".join(lines)

    # Master review document
    master_lines = [
        "# RAGTune Benchmark v0: Comprehensive Human Review Packet\n",
        f"**Target**: 140 Development Benchmark Queries Grounded in Validation Partition\n",
        f"**Audit Status**: UNREVIEWED (Pending Review by Satish)\n",
        f"**Quality Audit Summary**:\n",
        f"- Total Queries: {len(queries)}\n",
        f"- Ecosystems: 35 PostgreSQL, 35 PyTorch, 35 Kubernetes, 35 FastAPI\n",
        f"- Typologies: 40 Direct Lookup, 60 Comparative Discrimination, 40 Troubleshooting Scenario\n",
        f"- Truthful Provenance: 88 AI Authored Project Queries, 49 Synthetic Grounded, 3 External Derived Verified\n",
        f"- Relevance Positives: 22 with 1 positive, 108 with 2 positives, 10 with 3+ positives\n",
        f"- Uncertainty Candidates: {quality_audit['uncertainty_audit']['total_uncertain']} queries flagged\n\n",
        "---\n\n",
    ]

    domain_queries: Dict[str, List[Dict[str, Any]]] = {}
    for q in queries:
        domain_queries.setdefault(q["domain"], []).append(q)

    # Build master document
    idx = 1
    for domain, d_queries in domain_queries.items():
        master_lines.append(f"## {domain.upper()} EVALUATION QUERIES ({len(d_queries)} Queries)\n\n")
        for q in d_queries:
            master_lines.append(format_query_markdown(q, idx))
            idx += 1

    master_path = review_dir / "benchmark_v0_review.md"
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(master_lines))
    print(f"Saved master human review packet to: {master_path}")

    # Build individual domain sub-packets for easier review
    for domain, d_queries in domain_queries.items():
        sub_lines = [
            f"# Benchmark v0 Review Packet: {domain.upper()} ({len(d_queries)} Queries)\n",
            f"**Reviewer**: Satish | **Status**: UNREVIEWED\n\n",
            "---\n\n",
        ]
        for sub_idx, q in enumerate(d_queries, start=1):
            sub_lines.append(format_query_markdown(q, sub_idx))

        sub_path = review_dir / f"{domain}_review.md"
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write("\n".join(sub_lines))
        print(f"Saved {domain} review sub-packet to: {sub_path}")

    # Build CSV review sheet
    csv_path = review_dir / "benchmark_v0_review.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "query_id", "domain", "typology", "provenance_type", "query_text",
            "positives_count", "uncertainty", "ai_recommendation",
            "review_status", "reviewer", "review_notes"
        ])
        for q in queries:
            writer.writerow([
                q["query_id"],
                q["domain"],
                q["typology"],
                q["provenance_type"],
                q["query_text"],
                len(q["relevant_chunks"]),
                q["uncertainty"],
                q.get("ai_recommendation", "APPROVE_CANDIDATE"),
                q.get("review_status", "UNREVIEWED"),
                q.get("reviewer", ""),
                q.get("review_notes", ""),
            ])
    print(f"Saved CSV review sheet to: {csv_path}")

    # Build JSON review sheet
    json_path = review_dir / "benchmark_v0_review.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(queries, f, indent=2)
    print(f"Saved JSON review sheet to: {json_path}")

    # Build dedicated 40-query human audit packet
    generate_human_audit_packet()


if __name__ == "__main__":
    main()
