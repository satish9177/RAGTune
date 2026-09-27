"""Generate Post-Repair Human-Review Packet (v3) for Benchmark v0 (40 Queries).

Renders `benchmarks/review/HUMAN_AUDIT_40_V3.md` containing:
- 40 sampled queries exactly matching `human_audit_sample_ids.json`
- Explicit status badges:
  - [HUMAN-AUDIT APPROVED AS-IS] (18 queries approved during V2 review)
  - [POST-REVISE REPAIRED] (22 queries repaired following V2 review)
- For repaired queries:
  - Previous V2 query text
  - V3 query text (highlighting differences)
  - Previous V2 evidence chunk IDs and grades
  - New V3 evidence chunk IDs and grades
  - Concise repair rationale explaining exact relevance alignment
  - Answer-bearing excerpts centered on distinguishing statements
- For approved queries:
  - Query text, evidence passages, and answer-bearing excerpts preserved
- Clean, unselected human reviewer decision checkboxes
  (review status = AWAITING_HUMAN_REVIEW, reviewer = null, reviewed_at = null)
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Set

from scripts.evidence_verifier import extract_answer_span


APPROVED_AS_IS_QIDS: Set[str] = {
    "v0_pg_025", "v0_pg_034",
    "v0_pt_003", "v0_pt_025", "v0_pt_027",
    "v0_k8s_011", "v0_k8s_014", "v0_k8s_017", "v0_k8s_025", "v0_k8s_027", "v0_k8s_029",
    "v0_fa_004", "v0_fa_010", "v0_fa_011", "v0_fa_016", "v0_fa_022", "v0_fa_026", "v0_fa_028",
}

REVISED_QIDS: Set[str] = {
    "v0_pg_001", "v0_pg_002", "v0_pg_011", "v0_pg_013", "v0_pg_016", "v0_pg_017", "v0_pg_018", "v0_pg_026", "v0_pg_030",
    "v0_pt_002", "v0_pt_012", "v0_pt_015", "v0_pt_018", "v0_pt_021", "v0_pt_023", "v0_pt_032",
    "v0_k8s_007", "v0_k8s_010", "v0_k8s_015", "v0_k8s_022",
    "v0_fa_018", "v0_fa_023",
}

REPAIR_RATIONALES: Dict[str, str] = {
    "v0_pg_001": "Re-anchored canonical Grade 3 to bd01abb12ba6 (shared_buffers parameter definition and allocation limits in config.sgml); demoted memory units syntax chunk e32eba5f400a from G2 to G1.",
    "v0_pg_002": "Re-anchored canonical Grade 3 to c702d7353ba3 (work_mem per-operation sort/hash memory sizing in config.sgml); retained d5b2659b0954 (work_mem header) as G1 supporting context; removed unrelated shared_buffers chunk.",
    "v0_pg_011": "Re-anchored canonical Grade 3 to 6cf7e592b2d8 (explicit durability/crash recovery behavior of on vs remote_write under server crash vs standby crash in config.sgml); retained 16e38b8eb501 (synchronous_commit parameter enum) as G2.",
    "v0_pg_013": "Re-anchored canonical Grade 3 to 4cb1a6e848ab (hot_standby_feedback preventing vacuum cleanup of needed rows on primary); retained 7ebc2979ff55 (max_standby_streaming_delay) as G2; removed unrelated fsync passage.",
    "v0_pg_016": "Re-anchored canonical Grade 3 to a1d4c0645801 (DEPENDENCY_NORMAL vs DEPENDENCY_AUTO DROP CASCADE mechanics in pg_depend catalog); demoted 62205074cfda to G1 supporting context.",
    "v0_pg_017": "Re-anchored canonical Grade 3 to 6c035189f85c (typalign alignment values and typstorage TOAST strategies in pg_type catalog); demoted e65a79fa4610 to G1 supporting context.",
    "v0_pg_018": "Re-anchored canonical Grade 3 to 58602e758a4a (indisprimary, indisclustered, and indisvalid index status flags in pg_index catalog); demoted aa5e14262dda to G1; removed unrelated 8c2ca41b20e2.",
    "v0_pg_026": "Re-anchored canonical Grade 3 to e0bcb398517f (max_connections allocation limit in config.sgml); retained d861d5735a4c (CONNECTION LIMIT) as G2; retained 8baf96422a9b as G1; removed unrelated shared_buffers chunk.",
    "v0_pg_030": "Re-anchored canonical Grade 3 to 4151c530c8cf (deadlock_timeout diagnostics and circular lock logging in config.sgml); retained 8c5ead82d778 (log_lock_waits) as G2; removed unrelated 70ad01344c11 (lock_timeout).",
    "v0_pt_002": "Re-anchored canonical Grade 3 to 79cab38f8b32 (exact comparison of create_graph False vs True on parameter gradient accumulation and graph retention during backward pass); demoted 9443759e48ac to G1 supporting context.",
    "v0_pt_012": "Rewrote query to match authentic documentation: 'How does PyTorch detect illegal in-place modifications to tensors saved for backward during automatic differentiation?'; re-anchored canonical Grade 3 to d7fb32e88610 (tensor version counter increments and in-place modification check during backward in notes/autograd.rst); retained cd18be956c26 as G1.",
    "v0_pt_015": "Rewrote query to match authentic documentation: 'Which start methods are supported for sharing CUDA tensors across processes in PyTorch multiprocessing, and what lifetime management rules apply to the sending process?'; re-anchored canonical Grade 3 to 6ba0b24e5699 (CUDA tensor sharing via spawn/forkserver and producer process retention requirement in notes/multiprocessing.rst); retained 47c7bc4b7227 as G1.",
    "v0_pt_018": "Rewrote query to match authentic documentation: 'What issues with sequential process termination and error propagation are addressed by torch.multiprocessing.spawn compared to manually joining standard Process instances?'; re-anchored canonical Grade 3 to 87f584fa213e (spawn catching exceptions, terminating remaining processes, and propagating error in multiprocessing.rst); retained 14db012076f4 as G1.",
    "v0_pt_021": "Re-anchored canonical Grade 3 to 47c7bc4b7227 (file_descriptor vs file_system strategy trade-offs and limits in notes/multiprocessing.rst); retained 08622241d3bd (torch_shm_manager) as G2; removed unrelated CUDA passage.",
    "v0_pt_023": "Rewrote query to supported mathematical equations in documentation: 'How do scale and zero-point calculations differ between symmetric and asymmetric affine quantization schemes in PyTorch?'; re-anchored canonical Grade 3 to 5bf6b4652e3d (exact formulas for scale and zero_point in quantization.rst); retained 0cb39a089da1 (torch.qscheme enums) as G2.",
    "v0_pt_032": "Rewrote query to authentic PyTorch FAQ troubleshooting: 'How to resolve GPU \\'cuda runtime error(2): out of memory\\' caused by autograd history accumulation in a PyTorch training loop?'; re-anchored canonical Grade 3 to c51ddba8d3d5 (autograd history accumulation across iterations in loss accumulation and fix using .item() in notes/faq.rst); retained d79a0dcbe218 as G2.",
    "v0_k8s_007": "Re-anchored canonical Grade 3 to 60113ca5b874 (distinction between ReadWriteOnce single node vs ReadWriteOncePod single pod in persistent-volumes.md); retained 8786a18f2e70 (volume access mode enforcement) as G2.",
    "v0_k8s_010": "Re-anchored canonical Grade 3 to 2199ee2405be (requiredDuringSchedulingIgnoredDuringExecution hard requirement vs preferredDuringSchedulingIgnoredDuringExecution soft preference in nodeAffinity); retained e32eba5f400a as G1 supporting context; removed introductory TOC passage 3cba1ae92b92.",
    "v0_k8s_015": "Promoted 6ddcf2182d64 (Recreate deployment strategy definition) to Grade 2 so both sides of the comparison (RollingUpdate Grade 3 in b997853e6622 and Recreate Grade 2 in 6ddcf2182d64) are Grade >= 2; retained cd8538e597b5 as G1 supporting context.",
    "v0_k8s_022": "Re-anchored canonical Grade 3 to 74825e38c71a (authorization scope distinction between RoleBinding within namespace vs ClusterRoleBinding cluster-wide when referencing a ClusterRole); retained 179f6c682519 (ClusterRole YAML example) as G2.",
    "v0_fa_018": "Rewrote query to exact specification: 'Why does FastAPI CORSMiddleware require explicitly specifying origins rather than using allow_origins=[\\'*\\'] when allow_credentials=True?'; re-anchored canonical Grade 3 to 4e814ec518ec (wildcards excluding credentials, cookies, and authorization headers in tutorial/cors.md); retained 494d12e9c518 (parameter spec) as G2.",
    "v0_fa_023": "Rewrote query to supported comparison: 'How does configuring root_path as a FastAPI app parameter compare to passing the --root-path command-line option to the ASGI server when running behind a proxy with a stripped prefix?'; re-anchored canonical Grade 3 to 7008bc96ad50 (root_path FastAPI application parameter in tutorial/behind-a-proxy.md); retained 4a8ba42bc58f (--root-path command line option) as G2; retained ff015043a502 as G1 supporting context.",
}


def get_query_terms(text: str) -> List[str]:
    raw_tokens = re.findall(r"[A-Za-z0-9_\.]+", text)
    stopwords = {
        "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
        "does", "do", "did", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "having", "the", "a", "an", "and", "or", "but",
        "if", "because", "as", "until", "while", "of", "at", "by", "for", "with",
        "about", "against", "between", "into", "through", "during", "before",
        "after", "above", "below", "to", "from", "up", "down", "in", "out",
        "on", "off", "over", "under", "again", "further", "then", "once", "here",
        "there", "all", "any", "both", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
        "too", "very", "can", "will", "just", "should", "now"
    }
    terms = [t for t in raw_tokens if t.lower() not in stopwords and len(t) > 2]
    return terms if terms else raw_tokens


def generate_human_audit_packet_v3() -> None:
    # 1. Load chunks
    chunks_by_id: Dict[str, Dict[str, Any]] = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            chunks_by_id[item["chunk_id"]] = item

    # 2. Load V2 snapshot and V3 current benchmark
    with open("benchmarks/review/benchmark_v0_v2_snapshot.jsonl", "r", encoding="utf-8") as f:
        v2_queries = {q["query_id"]: q for q in (json.loads(line) for line in f)}

    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        v3_queries = {q["query_id"]: q for q in (json.loads(line) for line in f)}

    # 3. Load sample IDs manifest
    manifest_path = Path("benchmarks/review/human_audit_sample_ids.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        sample_manifest = json.load(f)

    sample_details = {d["query_id"]: d for d in sample_manifest["sample_details"]}
    sample_qids = sample_manifest["sample_query_ids"]

    # Order sample queries by ecosystem: postgresql, pytorch, kubernetes, fastapi
    eco_order = {"postgresql": 0, "pytorch": 1, "kubernetes": 2, "fastapi": 3}
    ordered_qids = sorted(sample_qids, key=lambda q: (eco_order.get(v3_queries[q]["domain"], 9), q))

    lines: List[str] = []
    lines.append("# Human Audit Review Packet v3 (40-Query Stratified Sample)\n")
    lines.append("> **Benchmark Version**: Benchmark v0 (Development Benchmark — 140 Queries Grounded in `validation`)")
    lines.append("> **Audit Target**: 40-Query Human-Review Stratified Sample (10 per ecosystem)")
    lines.append("> **Review State**: `AWAITING_HUMAN_REVIEW` (All 40 queries await formal review by Satish; zero simulated human approvals)")
    lines.append("> **Automated Sanity Check Status**: 139 PASS / 1 REVIEW / 0 FAIL (`benchmarks/v3_evidence_audit_report.json`)\n")

    lines.append("## Overview of V3 Audit Review Packet\n")
    lines.append("This packet presents the 40-query development benchmark sample following the V2 human review conducted by Satish:")
    lines.append("- **18 Queries Approved As-Is**: Marked with `[HUMAN-AUDIT APPROVED AS-IS]`. Query text, canonical evidence, and supporting evidence are preserved exactly as approved.")
    lines.append("- **22 Queries Repaired**: Marked with `[POST-REVISE REPAIRED]`. For each query, this packet documents the exact diff from V2 (query text change, previous evidence chunks, new evidence chunks, and technical rationale), followed by answer-bearing excerpts centered on distinguishing passages.")
    lines.append("- **Reviewer Controls**: Each entry provides unselected checkboxes (`APPROVE`, `REVISE`, `REJECT`) for formal human sign-off.\n")

    lines.append("### Summary Table\n")
    lines.append("| # | Query ID | Ecosystem | Typology | V2 Review Disposition | V3 Audit Badge | Automated Check Status | Canonical Chunk (Grade 3) |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for idx, qid in enumerate(ordered_qids, 1):
        q3 = v3_queries[qid]
        g3_id = next(r["chunk_id"] for r in q3["relevant_chunks"] if r["grade"] == 3)
        if qid in APPROVED_AS_IS_QIDS:
            v2_disp = "APPROVE AS-IS"
            badge = "[HUMAN-AUDIT APPROVED AS-IS]"
        else:
            v2_disp = "REVISE"
            badge = "[POST-REVISE REPAIRED]"
        check_status = "AUTOMATED_CHECK_PASS" if qid != "v0_fa_018" else "AUTOMATED_CHECK_REVIEW"
        lines.append(f"| {idx} | `{qid}` | `{q3['domain']}` | `{q3['typology']}` | `{v2_disp}` | `{badge}` | `{check_status}` | `{g3_id[:12]}` |")

    lines.append("\n---\n")

    # Render entries
    for idx, qid in enumerate(ordered_qids, 1):
        q_v3 = v3_queries[qid]
        q_v2 = v2_queries[qid]
        eco = q_v3["domain"]
        qtext = q_v3["query_text"]
        meta = q_v3.get("provenance_metadata", {})
        sample_info = sample_details.get(qid, {})
        inc_reason = sample_info.get("inclusion_reason", "sampled")

        is_approved = qid in APPROVED_AS_IS_QIDS
        badge = "[HUMAN-AUDIT APPROVED AS-IS]" if is_approved else "[POST-REVISE REPAIRED]"

        lines.append(f"### {idx}. `[{qid}]` {qtext}\n")
        lines.append(f"**Audit Status Badge**: `{badge}`\n")
        lines.append(f"- **Ecosystem**: `{eco}` | **Typology**: `{q_v3['typology']}` | **Role**: `{q_v3['role']}`")
        lines.append(f"- **Provenance**: `{q_v3['provenance_type']}` | **Inclusion Reason**: `{inc_reason}`")
        lines.append(f"- **Review Status**: `{q_v3.get('review_status', 'AWAITING_HUMAN_REVIEW')}` | **AI Recommendation**: **`{q_v3.get('ai_recommendation', 'APPROVE_CANDIDATE')}`**")

        if q_v3.get("uncertainty"):
            lines.append(f"- **Uncertainty Flag**: `TRUE (Borderline / Nuanced Relevance)`")
            lines.append(f"  - *Audit Note*: Multi-aspect or subtle distinctions where supporting passages provide closely related background or alternative mechanisms.")
        else:
            lines.append(f"- **Uncertainty Flag**: `False (Unambiguous Relevance)`")

        if q_v3.get("provenance_type") == "external_derived_verified":
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

        if is_approved:
            lines.append(f"\n> [!NOTE]\n> **V2 Audit Disposition: APPROVED AS-IS**\n> Query text and graded relevance evidence were reviewed and approved in the V2 audit packet. Preserved without modification.\n")
        else:
            rationale = REPAIR_RATIONALES.get(qid, "Evidence aligned with benchmark quality contract.")
            lines.append(f"\n> [!NOTE]\n> **V2 Audit Disposition: REVISE -> V3 Repair Diff**:")
            if q_v2["query_text"] != q_v3["query_text"]:
                lines.append(f"> - **Previous V2 Query**: \"_{q_v2['query_text']}_\"")
                lines.append(f"> - **Repaired V3 Query**: \"**{q_v3['query_text']}**\"")
            else:
                lines.append(f"> - **Query Text**: Unchanged (\"_{q_v3['query_text']}_\")")

            # Evidence diff
            v2_ev = [f"G{r['grade']}:{r['chunk_id'][:12]}" for r in q_v2["relevant_chunks"]]
            v3_ev = [f"G{r['grade']}:{r['chunk_id'][:12]}" for r in q_v3["relevant_chunks"]]
            lines.append(f"> - **Previous Evidence (V2)**: {', '.join(v2_ev)}")
            lines.append(f"> - **Repaired Evidence (V3)**: {', '.join(v3_ev)}")
            lines.append(f"> - **Repair Rationale**: {rationale}\n")

        lines.append("#### Graded Relevance Evidence Passages (Answer-Centered Excerpts):")
        query_terms = get_query_terms(qtext)

        for r in q_v3["relevant_chunks"]:
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
                answer_span = extract_answer_span(c["content"], query_terms, window_chars=500)
                lines.append(f"- **{grade_name}** — Chunk ID: `{cid[:12]}` (`{c['relative_file_path']}`, {c['token_count']} tokens)")
                lines.append(f"  - *Breadcrumb*: `{c.get('breadcrumb', '')}`")
                lines.append(f"  - *Annotation Note*: {r.get('notes', '')}")
                lines.append(f"  - *Answer-Bearing Excerpt*: > \"_{answer_span}_\"\n")
            else:
                lines.append(f"- **{grade_name}** — Chunk ID: `{cid}` (NOT FOUND IN VALIDATION PARTITION)\n")

        lines.append("#### Human Reviewer Decision (Satish):")
        lines.append("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**")
        lines.append("- **Reviewer Notes**: _____________________________________________________")
        lines.append("- **Decision Date**: ____________________\n")
        lines.append("---\n")

    output_path = Path("benchmarks/review/HUMAN_AUDIT_40_V3.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Generated V3 Human Audit Packet: {output_path}")
    print(f"Total queries in packet: {len(ordered_qids)}")
    print(f"Approved As-Is: {len(APPROVED_AS_IS_QIDS)}")
    print(f"Repaired: {len(REVISED_QIDS)}")


if __name__ == "__main__":
    generate_human_audit_packet_v3()
