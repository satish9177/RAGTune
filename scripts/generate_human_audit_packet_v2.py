"""Generate Post-Repair Human-Review Packet (v2) for Benchmark v0 (40 Queries).

Renders `benchmarks/review/HUMAN_AUDIT_40_V2.md` containing:
- 40 sampled queries exactly matching `human_audit_sample_ids.json`
- Explicit previous review badges:
  - [PREVIOUSLY APPROVED - EVIDENCE PRESERVED] (5 queries)
  - [PREVIOUSLY REJECTED - QUERY & EVIDENCE REPLACED] (1 query: v0_pt_027)
  - [PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED] (6 queries)
  - [PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED] (28 queries)
- Answer-bearing excerpts extracted via extract_answer_span()
- Detailed diff and repair rationale explaining changes from v1
- Clean, unselected human reviewer decision checkboxes
  (review status = AWAITING_HUMAN_REVIEW, reviewer = null, reviewed_at = null)
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List

from scripts.evidence_verifier import extract_answer_span


REPAIR_ANNOTATIONS: Dict[str, Dict[str, str]] = {
    # --- PREVIOUSLY APPROVED (5) ---
    "v0_pt_025": {
        "badge": "[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]",
        "repair_rationale": "Grade 3 evidence (e3e6f9d3bdf9 in notes/autograd.rst) was reviewed and approved as the exact answer-bearing passage defining the autograd anomaly detection mode and detect_anomaly() context manager. Evidence preserved without modification.",
    },
    "v0_k8s_011": {
        "badge": "[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]",
        "repair_rationale": "Grade 3 evidence (4c4755e1dbba in deployment.md) was reviewed and approved for Deployment pause/resume rollout behavior. Evidence preserved without modification.",
    },
    "v0_fa_004": {
        "badge": "[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]",
        "repair_rationale": "Grade 3 evidence (9b2fa9552912 in header-params.md) was reviewed and approved for automatic snake_case to kebab-case conversion of HTTP headers in FastAPI. Evidence preserved without modification.",
    },
    "v0_fa_026": {
        "badge": "[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]",
        "repair_rationale": "Grade 3 evidence (08b6b6be9fbc in behind-a-proxy.md) was reviewed and approved for Swagger UI /docs OpenAPI schema failure behind reverse proxy (root_path). Evidence preserved without modification.",
    },
    "v0_fa_028": {
        "badge": "[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]",
        "repair_rationale": "Grade 3 evidence (76f8021c430e in behind-a-proxy.md) was reviewed and approved for reverse proxy prefix configuration and redirect behavior. Evidence preserved without modification.",
    },

    # --- PREVIOUSLY REJECTED (1) ---
    "v0_pt_027": {
        "badge": "[PREVIOUSLY REJECTED - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about DataLoader worker /dev/shm bus error, but PyTorch validation partition documentation did not contain /dev/shm coverage. Query and evidence completely replaced with authentic PyTorch troubleshooting scenario from notes/faq.rst: CUDA Out of Memory (OOM) exception handler traceback reference cycle memory leak and mitigation via local variable scoping (1599a13b824d).",
    },

    # --- PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED (6) ---
    "v0_pg_016": {
        "badge": "[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about replication LSNs (sent_lsn, write_lsn), which were unsupported in validation partition. Replaced with pg_depend dependency types query (DEPENDENCY_NORMAL vs DEPENDENCY_AUTO). Evidence anchored in catalogs.sgml (a1d4c0645801).",
    },
    "v0_pg_017": {
        "badge": "[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about pg_tablespace location symlinks, absent from validation partition. Replaced with pg_type physical storage alignment (typalign) and TOAST strategies (typstorage). Evidence anchored in catalogs.sgml (6c035189f85c).",
    },
    "v0_pg_018": {
        "badge": "[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about pg_stat_user_tables dead tuples, absent from partition. Replaced with pg_index column flags (indisprimary, indisclustered, indisvalid). Evidence anchored in catalogs.sgml (58602e758a4a).",
    },
    "v0_pt_002": {
        "badge": "[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about autograd backward graph retention generically. Replaced with precise query on param.grad accumulation semantics under repeated backward() / create_graph. Evidence anchored in notes/autograd.rst (79cab38f8b32).",
    },
    "v0_pt_012": {
        "badge": "[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about autograd anomaly detection stack traces broadly. Replaced with precise query on in-place modification version counter checking and error handling during backward pass. Evidence anchored in notes/autograd.rst (d7fb32e88610).",
    },
    "v0_k8s_017": {
        "badge": "[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]",
        "repair_rationale": "In v1, query asked about broad PersistentVolume types. Replaced with precise query on PersistentVolume reclaim policies (Retain vs Delete) and volume lifecycle when PVC is deleted. Evidence anchored in persistent-volumes.md (7488aa8c4d1a).",
    },

    # --- PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED (28) ---
    "v0_pg_001": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to generic unit definitions table (e3a08cb99b2a). Re-anchored Grade 3 to exact shared_buffers configuration specification (bd01abb12ba6).",
    },
    "v0_pg_002": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to temp_buffers passage (d5b2659b0954). Re-anchored Grade 3 to exact work_mem configuration specification (c702d7353ba3).",
    },
    "v0_pg_011": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to fsync explanation (16e38b8eb501). Re-anchored Grade 3 to exact synchronous_commit level definitions (6cf7e592b2d8).",
    },
    "v0_pg_013": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 and Grade 2 were reversed (4cb1a6e848ab / b239bf42ebfe). Re-anchored Grade 3 to hot_standby_feedback definition and delay comparison (b239bf42ebfe, 4cb1a6e848ab).",
    },
    "v0_pg_025": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to checkpoint tuning overview. Re-anchored Grade 3 to background writer vs checkpointer dirty buffer management in config.sgml (de7f7a398fba).",
    },
    "v0_pg_026": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to locks overview without cancellation details. Re-anchored Grade 3 to explicit deadlock detection and deadlock_timeout statement cancellation (39efbcf9d2c3).",
    },
    "v0_pg_030": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to vacuum routine syntax. Re-anchored Grade 3 to transaction wraparound vacuum freezing and autovacuum emergency action (f3e39b7a4218).",
    },
    "v0_pg_034": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to replication concepts. Re-anchored Grade 3 to archive_command failure causing WAL segment buildup in pg_wal (83e90d3185f7).",
    },
    "v0_pt_003": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to high-level backward intro. Re-anchored Grade 3 to explicit torch.autograd.grad tensor output computation and graph inspection (cd18be956c26).",
    },
    "v0_pt_015": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to tensor copy intro. Re-anchored Grade 3 to non-blocking CUDA memory transfer semantics and pinned memory requirements (b8dfd6eb34f1).",
    },
    "v0_pt_018": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to multiprocessing overview. Re-anchored Grade 3 to DataLoader pin_memory=True page-locked staging memory behavior (364feffb2a09).",
    },
    "v0_pt_021": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to inference tutorial intro. Re-anchored Grade 3 to exact comparison between torch.no_grad() and torch.inference_mode() view tracking differences (96ca8d415715).",
    },
    "v0_pt_023": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to tensor dimensionality table. Re-anchored Grade 3 to PyTorch broadcasting semantics and dimension alignment rules (49f7b11568da).",
    },
    "v0_pt_032": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to general multiprocessing intro. Re-anchored Grade 3 to DataLoader multithreading CUDA initialization error and fork vs spawn fix in notes/faq.rst (e497fbbd960d).",
    },
    "v0_k8s_007": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to Pod specification overview. Re-anchored Grade 3 to Pod Disruption Budgets (minAvailable / maxUnavailable) in pod-disruption-budget.md (99bc45cb5757).",
    },
    "v0_k8s_010": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to Deployments intro (A _Deployment_ provides declarative updates). Re-anchored Grade 3 to .spec.strategy.type RollingUpdate parameters in deployment.md (4c4755e1dbba).",
    },
    "v0_k8s_014": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to scheduling intro. Re-anchored Grade 3 to exact differences between podAffinity and nodeAffinity targeting pod labels vs node labels in assign-pod-node.md (9a1e8ed08b62).",
    },
    "v0_k8s_015": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to DNS service discovery overview. Re-anchored Grade 3 to ClusterFirst vs Default pod DNS policies in dns-pod-service.md (ebf5221b66df).",
    },
    "v0_k8s_022": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to Deployments summary intro. Re-anchored Grade 3 to Deployment maxSurge vs maxUnavailable rolling update semantics in deployment.md (4c4755e1dbba).",
    },
    "v0_k8s_025": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to Pod lifecycle phases table. Re-anchored Grade 3 to preStop hook vs terminationGracePeriodSeconds lifecycle execution in pod-lifecycle.md (9bebf9b48957).",
    },
    "v0_k8s_027": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to generic container troubleshooting. Re-anchored Grade 3 to CrashLoopBackOff troubleshooting and exponential backoff restart delays in debug-running-pod.md (7036e8894101).",
    },
    "v0_k8s_029": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to container images overview. Re-anchored Grade 3 to ImagePullBackOff authorization and pull secret debugging in pull-image-private-registry.md (38e4a9e3ae43).",
    },
    "v0_fa_010": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to generic parameter intro. Re-anchored Grade 3 to Field() validation parameter definitions (gt, ge, regex) in body-fields.md (5928a6f3b0e3).",
    },
    "v0_fa_011": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to async intro paragraph. Re-anchored Grade 3 to def threadpool worker execution vs async def event loop concurrency in async-sql.md / async.md (77a28e9323fa).",
    },
    "v0_fa_016": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to security overview. Re-anchored Grade 3 to Depends() vs Security() dependency scope verification and OpenAPI security declarations in security/first-steps.md (f9bf2a9d80d2).",
    },
    "v0_fa_018": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to events intro. Re-anchored Grade 3 to FastAPI lifespan context manager vs legacy startup/shutdown events in events.md (c03bc9876251).",
    },
    "v0_fa_022": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to middleware intro. Re-anchored Grade 3 to FastAPI middleware vs dependency injection execution order in middleware.md (6bc3ef1284d7).",
    },
    "v0_fa_023": {
        "badge": "[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]",
        "repair_rationale": "In v1, Grade 3 pointed to handling errors intro. Re-anchored Grade 3 to custom exception handler inheritance and RequestValidationError override in handling-errors.md (74cf5aa15fec).",
    },
}


def get_query_terms(qtext: str) -> List[str]:
    """Extract salient search terms for excerpt centering."""
    raw_tokens = re.findall(r"[A-Za-z0-9_.]+", qtext)
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


def format_audit_query_markdown_v2(
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

    annotation = REPAIR_ANNOTATIONS.get(qid, {
        "badge": "[POST-REPAIR REVIEW]",
        "repair_rationale": "Evidence aligned with benchmark quality contract.",
    })
    badge = annotation["badge"]
    rationale = annotation["repair_rationale"]

    lines.append(f"### {idx}. `[{qid}]` {qtext}\n")
    lines.append(f"**Audit Status Badge**: `{badge}`\n")
    lines.append(f"- **Ecosystem**: `{eco}` | **Typology**: `{q['typology']}` | **Role**: `{q['role']}`")
    lines.append(f"- **Provenance**: `{q['provenance_type']}` | **Inclusion Reason**: `{inc_reason}`")
    lines.append(f"- **Review Status**: `{q.get('review_status', 'AWAITING_HUMAN_REVIEW')}` | **AI Recommendation**: **`{q.get('ai_recommendation', 'APPROVE_CANDIDATE')}`**")

    if q.get("uncertainty"):
        lines.append(f"- **Uncertainty Flag**: `TRUE (Borderline / Nuanced Relevance)`")
        lines.append(f"  - *Audit Rationale*: Query involves multi-aspect or subtle distinctions where supporting passages provide closely related background or alternative mechanisms.")
    else:
        lines.append(f"- **Uncertainty Flag**: `False (Unambiguous Relevance)`")

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

    lines.append(f"\n> [!NOTE]\n> **Repair Explanation / Diff from v1**:\n> {rationale}\n")

    lines.append("#### Graded Relevance Evidence Passages (Answer-Centered Excerpts):")
    query_terms = get_query_terms(qtext)

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
            # Extract centered answer span
            answer_span = extract_answer_span(c["content"], query_terms, window_chars=320)
            lines.append(f"- **{grade_name}** — Chunk ID: `{cid[:12]}` (`{c['relative_file_path']}`, {c['token_count']} tokens)")
            lines.append(f"  - *Breadcrumb*: `{c['breadcrumb']}`")
            lines.append(f"  - *Annotation Note*: {r.get('notes', '')}")
            lines.append(f"  - *Answer-Bearing Excerpt*: > \"_{answer_span}_\"\n")
        else:
            lines.append(f"- **{grade_name}** — Chunk ID: `{cid}` (NOT FOUND IN VALIDATION PARTITION)\n")

    lines.append("#### Human Reviewer Decision (Satish):")
    lines.append("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**")
    lines.append("- **Reviewer Notes**: _____________________________________________________")
    lines.append("- **Decision Date**: ____________________\n")
    lines.append("---\n")
    return "\n".join(lines)


def generate_human_audit_packet_v2():
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
        "# RAGTune Benchmark v0: Post-Repair 40-Query Human Audit Packet (v2)\n",
        f"**Target**: Deterministic 40-Query Human Review Sample of Benchmark v0 (Post-Repair)\n",
        f"**Auditor**: Satish (Human Reviewer) | **Current State**: `AWAITING_HUMAN_REVIEW`\n",
        f"**Random Seed**: 42 | **Sampling Strategy**: `deterministic_stratified_v1`\n\n",
        "> [!IMPORTANT]",
        "> **Benchmark v0 Freeze Contract**: Benchmark v0 will be officially frozen only after Satish completes human review of this 40-query audit packet.",
        "> All 40 queries currently remain in `AWAITING_HUMAN_REVIEW` state with null reviewer signatures. Zero human decisions have been simulated by the AI assistant.",
        "> This v2 packet incorporates all repairs requested in the v1 human review recommendations:\n",
        "> - **Approved Queries (5)**: Evidence preserved exactly as verified.\n",
        "> - **Rejected Query (1 - `v0_pt_027`)**: Replaced with authentic PyTorch OOM exception handler traceback cycle leak.\n",
        "> - **Revised Queries (34)**: Re-anchored to exact answer-bearing spans (zero generic intros/TOCs), with 6 queries replaced where the ecosystem partition lacked specific target coverage.\n\n",
        "## Audit Sample Composition\n",
        "| Category | Count | Description |",
        "| :--- | :--- | :--- |",
        f"| **Uncertainty Flagged** | {sample_manifest['composition']['uncertain_queries']} | 100% of queries identified with borderline or multi-aspect relevance |",
        f"| **Verified External Queries** | {sample_manifest['composition']['external_verified_queries']} | 100% of Stack Overflow questions with exact revision/license tracking |",
        f"| **Stratified Additional Sample** | {sample_manifest['composition']['stratified_additional_queries']} | Deterministically sampled across all 4 ecosystems and typologies (seed=42) |",
        f"| **Total Audit Sample** | **{len(ordered_sample_queries)}** | **Full representative sample (28.6% of 140 benchmark queries)** |\n\n",
        "### Review Status Badges Breakdown\n",
        "- `[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]`: **5 queries** (`v0_pt_025`, `v0_k8s_011`, `v0_fa_004`, `v0_fa_026`, `v0_fa_028`)",
        "- `[PREVIOUSLY REJECTED - QUERY & EVIDENCE REPLACED]`: **1 query** (`v0_pt_027`)",
        "- `[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]`: **6 queries** (`v0_pg_016`, `v0_pg_017`, `v0_pg_018`, `v0_pt_002`, `v0_pt_012`, `v0_k8s_017`)",
        "- `[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]`: **28 queries**",
        "- **Total**: **40 queries**\n\n",
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
        "| # | Query ID | Ecosystem | Typology | Review Status Badge | Inclusion Reason | AI Rec |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for idx, q in enumerate(ordered_sample_queries, start=1):
        s_info = sample_details.get(q["query_id"], {})
        reason = s_info.get("inclusion_reason", "")
        badge = REPAIR_ANNOTATIONS.get(q["query_id"], {}).get("badge", "[POST-REPAIR REVIEW]")
        doc_lines.append(
            f"| {idx} | `{q['query_id']}` | `{q['domain']}` | `{q['typology']}` | `{badge}` | `{reason}` | `{q.get('ai_recommendation', 'APPROVE_CANDIDATE')}` |"
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
            doc_lines.append(format_audit_query_markdown_v2(q, s_info, chunks_by_id, global_idx))
            global_idx += 1

    out_path = Path("benchmarks/review/HUMAN_AUDIT_40_V2.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(doc_lines))

    print(f"Generated post-repair human audit packet with {len(ordered_sample_queries)} queries: {out_path}")
    return out_path


if __name__ == "__main__":
    generate_human_audit_packet_v2()
