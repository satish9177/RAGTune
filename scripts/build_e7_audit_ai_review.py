"""Build AI review of E7_NEGATIVE_AUDIT_40 recording quality gate failure."""

from __future__ import annotations

import json
from pathlib import Path

FN_ITEMS = {
    11: ("train_py_0126", "Same document (torch.compiler_guards_overview.rst) detailing downstream VariableBuilder and VariableTracker logic directly addressing Guards Variables."),
    16: ("train_py_0141", "Same document (distributed.rst) explaining TORCH_DISTRIBUTED_DEBUG usage, monitored_barrier, and debug log levels."),
    17: ("train_py_0151", "Same document (notes/cuda.rst) explaining CUDA device semantics and tensor device assignment best practices."),
    21: ("train_ku_0265", "Same document (reference/access-authn-authz/extensible-admission-controllers.md) showing webhook POST requests with AdmissionReview API object structure."),
    22: ("train_ku_0268", "Same document (concepts/scheduling-eviction/pod-priority-preemption.md) explaining how to configure priorityClassName in Pod specs."),
    26: ("train_ku_0278", "Same document (tasks/administer-cluster/network-policy-provider/romana-network-policy.md) containing procedural instructions for installing and applying Romana network policy."),
    28: ("train_ku_0289", "Same document (tasks/administer-cluster/network-policy-provider/antrea-network-policy.md) containing procedural instructions for deploying Antrea CNI on Kubernetes."),
    29: ("train_ku_0299", "Candidate from horizontal-pod-autoscale.md substantively explains how HPA interacts with spec.replicas in Deployments/StatefulSets."),
    32: ("train_fa_0383", "Candidate from features.md explicitly defines and validates both dict and list Python data types in FastAPI."),
    33: ("train_fa_0384", "Same document (deployment/concepts.md) explaining automatic restarts and process managers for crash recovery."),
    35: ("train_fa_0387", "Same document (tutorial/extra-models.md) explaining how user_in maps to UserIn / UserInDB."),
    36: ("train_fa_0392", "Candidate from advanced/security/oauth2-scopes.md explains the get_current_user dependency tree and security scope propagation."),
    37: ("train_fa_0393", "Candidate from advanced/security/oauth2-scopes.md explains how get_current_user is configured as a dependency."),
}

AMB_ITEMS = {
    5: ("train_po_0018", "Candidate from alter_subscription.sgml covers logical replication constraint error skipping, semantically adjacent to subscription warnings."),
    7: ("train_po_0022", "Same document (lobj.sgml) discussing server-side lo_read and lo_write function calls."),
    8: ("train_po_0028", "Candidate explains postgresql.conf parameter settings and reload behavior without restart, covering one side of the comparative query."),
    13: ("train_py_0131", "Candidate from fx.rst provides code example of torch.fx.symbolic_trace, directly addressing one side of the comparative query."),
    27: ("train_ku_0287", "Same document (reference/access-authn-authz/kubelet-tls-bootstrapping.md) explaining --client-ca-file and certificate authentication."),
    30: ("train_ku_0300", "Same document (tasks/debug/debug-cluster/resource-metrics-pipeline.md) discussing kubelet node metrics and Kubernetes API access."),
    34: ("train_fa_0385", "Same document (tutorial/extra-models.md) discussing response declarations with plain arbitrary dict and Pydantic models."),
}


def main():
    in_path = Path("data/training/E7_NEGATIVE_AUDIT_40.json")
    out_json = Path("data/training/E7_NEGATIVE_AUDIT_40_AI_REVIEW.json")
    out_md = Path("data/training/E7_NEGATIVE_AUDIT_40_AI_REVIEW.md")

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reviewed_items = []
    for it in data["audit_items"]:
        idx = it["item_index"]
        qid = it["query_id"]
        if idx in FN_ITEMS:
            status = "FALSE_NEGATIVE"
            notes = FN_ITEMS[idx][1]
        elif idx in AMB_ITEMS:
            status = "AMBIGUOUS_UNSAFE"
            notes = AMB_ITEMS[idx][1]
        else:
            status = "TRUE_NEGATIVE"
            notes = "Candidate discusses distinct entity or unrelated subsystem; legitimate non-relevant confuser."

        reviewed_items.append({
            "item_index": idx,
            "query_id": qid,
            "ecosystem": it["ecosystem"],
            "typology": it.get("typology", "direct_lookup"),
            "query_text": it["query_text"],
            "positive_chunk_id": it["positive_chunk_id"],
            "positive_source_path": it["positive_source_path"],
            "hard_negative_chunk_id": it["hard_negative_chunk_id"],
            "hard_negative_source_path": it["hard_negative_source_path"],
            "mining_retriever": it["mining_retriever"],
            "hybrid_rank": it.get("hybrid_rank"),
            "rrf_score": it.get("rrf_score"),
            "teacher_scores": it["teacher_scores"],
            "ai_review": {
                "decision": status,
                "notes": notes,
                "is_human_decision": False,
                "human_reviewer": None,
                "human_approval_status": "PENDING_SATISH_HUMAN_REVIEW",
            }
        })

    status_counts = {
        "TRUE_NEGATIVE": sum(1 for it in reviewed_items if it["ai_review"]["decision"] == "TRUE_NEGATIVE"),
        "FALSE_NEGATIVE": sum(1 for it in reviewed_items if it["ai_review"]["decision"] == "FALSE_NEGATIVE"),
        "AMBIGUOUS_UNSAFE": sum(1 for it in reviewed_items if it["ai_review"]["decision"] == "AMBIGUOUS_UNSAFE"),
    }
    assert status_counts["TRUE_NEGATIVE"] == 20
    assert status_counts["FALSE_NEGATIVE"] == 13
    assert status_counts["AMBIGUOUS_UNSAFE"] == 7

    payload = {
        "audit_name": "E7_NEGATIVE_AUDIT_40_AI_REVIEW",
        "description": "AI-assisted diagnostic review of E7_NEGATIVE_AUDIT_40 detecting severe false-negative rate and circular teacher failure.",
        "status": "AI_REVIEW_FAILED_NEGATIVE_QUALITY_GATE",
        "human_decision_disclaimer": "These are AI review recommendations only. Do NOT record them as Satish human decisions.",
        "total_sample_size": 40,
        "classification_summary": status_counts,
        "audit_items": reviewed_items,
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Generated {out_json}")

    # Build Markdown report
    md_lines = [
        "# E7 Safe-Negative Audit: AI Review & Quality Gate Failure Report",
        "",
        "> [!CAUTION]",
        "> **AUDIT QUALITY GATE FAILED**: `AI_REVIEW_FAILED_NEGATIVE_QUALITY_GATE`",
        "> An AI-assisted semantic review of `E7_NEGATIVE_AUDIT_40.md` revealed a **32.5% False-Negative Rate** (13/40) and **17.5% Ambiguous/Unsafe Rate** (7/40).",
        "> Only 50.0% (20/40) of sampled items were confirmed as true negatives.",
        "> **Under no circumstances may E7 domain reranker training proceed with these candidates.**",
        "> These classifications are AI review recommendations only and do NOT represent Satish human signoff.",
        "",
        "## 1. Audit Summary",
        "",
        "- **Total Candidates Audited**: 40",
        "- **TRUE_NEGATIVE**: 20 (50.0%)",
        "- **FALSE_NEGATIVE**: 13 (32.5%) — **GATE FAILURE**",
        "- **AMBIGUOUS / UNSAFE**: 7 (17.5%)",
        "- **Gate Requirement**: ZERO FALSE_NEGATIVE, $\\le 2$ AMBIGUOUS.",
        "",
        "## 2. Root Cause Analysis: Circular Teacher Certification",
        "",
        "The previous mining pipeline relied circularly on `BAAI/bge-reranker-base` teacher margins as the primary determinant of `SAFE_NEGATIVE`:",
        "1. **Pretrained Model Blindspot**: As demonstrated in experiment E6, generic BGE reranker weights frequently misjudge technical documentation, assigning high confidence to general prose and low scores to concise YAML/code syntax.",
        "2. **Same-Document Subtopic Leaks**: Candidates residing in the exact same document as the positive were accepted if their breadcrumb differed slightly, allowing adjacent procedural steps and explanations to be labeled as negatives.",
        "3. **Entity Match Neglect**: When a query asked about a specific configuration key (e.g. `priorityClassName`), candidates containing that exact key and explaining how to use it in YAML were classified as safe negatives simply because the teacher produced a wide margin.",
        "4. **Comparative Query Asymmetry**: For comparative queries ('What is the difference between A and B'), candidates explaining A or B in full detail were labeled negatives because they did not explicitly mention the other entity.",
        "",
        "## 3. Itemized Failure Ledger",
        "",
        "### A. FALSE_NEGATIVE Items (13 Items — Disqualifying)",
        "",
        "| # | Query ID | Ecosystem | Query Text | Diagnostic Finding |",
        "|---:|---|---|---|---|",
    ]

    for idx in sorted(FN_ITEMS.keys()):
        item = next(it for it in reviewed_items if it["item_index"] == idx)
        md_lines.append(f"| {idx} | `{item['query_id']}` | {item['ecosystem']} | `{item['query_text'][:45]}...` | {FN_ITEMS[idx][1]} |")

    md_lines.extend([
        "",
        "### B. AMBIGUOUS / UNSAFE Items (7 Items)",
        "",
        "| # | Query ID | Ecosystem | Query Text | Diagnostic Finding |",
        "|---:|---|---|---|---|",
    ])

    for idx in sorted(AMB_ITEMS.keys()):
        item = next(it for it in reviewed_items if it["item_index"] == idx)
        md_lines.append(f"| {idx} | `{item['query_id']}` | {item['ecosystem']} | `{item['query_text'][:45]}...` | {AMB_ITEMS[idx][1]} |")

    md_lines.extend([
        "",
        "### C. TRUE_NEGATIVE Items (20 Items)",
        "",
        "| # | Query ID | Ecosystem | Query Text | Hybrid Rank | Teacher Margin |",
        "|---:|---|---|---|---:|---:|",
    ])

    for it in reviewed_items:
        if it["ai_review"]["decision"] == "TRUE_NEGATIVE":
            md_lines.append(f"| {it['item_index']} | `{it['query_id']}` | {it['ecosystem']} | `{it['query_text'][:50]}...` | #{it['hybrid_rank']} | {it['teacher_scores']['margin']:.4f} |")

    md_lines.append("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Generated {out_md}")


if __name__ == "__main__":
    main()
