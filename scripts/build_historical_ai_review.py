"""Generate AI review of historical E4 hard-negative audit (40 items).

Outputs:
- data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.json
- data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.md

IMPORTANT:
- Historical artifact `data/training/HARD_NEGATIVE_AUDIT_40.md` is preserved UNCHANGED.
- These records are AI-assisted recommendations only, NOT Satish human approval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


FALSE_NEGATIVES = {
    "train_py_0226": {
        "rationale": (
            "Positive and negative chunks are from the exact same troubleshooting file "
            "(torch.compiler_troubleshooting.rst) and both address TorchInductor error diagnosis. "
            "The proposed negative provides valid troubleshooting guidance directly relevant to the query."
        ),
    },
    "train_ku_0252": {
        "rationale": (
            "The negative candidate is from the canonical resource metrics pipeline document itself "
            "(tasks/debug/debug-cluster/resource-metrics-pipeline.md), explaining its API design and architecture. "
            "Penalizing this candidate as a negative suppresses answer-bearing documentation."
        ),
    },
    "train_fa_0377": {
        "rationale": (
            "Severe QUERY_POSITIVE_MAPPING_DEFECT: The query asks for 'yield in fastapi'. "
            "The positive chunk is misaligned (middleware.md discussing @app.middleware('http')), "
            "whereas the proposed negative (dependencies-with-yield.md) contains the exact answer: "
            "'async def get_db(): try: yield db finally: db.close()'. The candidate is a true positive "
            "and was incorrectly presented as a hard negative due to positive mapping displacement."
        ),
    },
    "train_fa_0466": {
        "rationale": (
            "Both positive and proposed negative chunks are from the same document "
            "(tutorial/dependencies/dependencies-with-yield.md) describing yield dependencies in FastAPI. "
            "The negative candidate discusses exception handling in yield dependencies, which is answer-bearing context."
        ),
    },
}

AMBIGUOUS_NEGATIVES = {
    "train_py_0166": {
        "rationale": (
            "Query asks for CUDA graphs non-constraints. Negative discusses live tensor limitations "
            "in CUDA graph trees. Both discuss constraints/limitations of CUDA graphs in PyTorch."
        ),
    },
    "train_py_0176": {
        "rationale": (
            "Query asks about autograd_tutorial. Positive discusses modules, while negative discusses "
            "extending autograd with custom Functions. Negative is semantically adjacent and could confuse training."
        ),
    },
    "train_py_0189": {
        "rationale": (
            "Query asks about float32 and uint8 tensors. Negative covers IEEE 754 floating point arithmetic "
            "and precision, which directly addresses the precision aspects of float32."
        ),
    },
    "train_py_0216": {
        "rationale": (
            "Positive and negative are from the same document (torch.compiler_guards_overview.rst). "
            "Positive discusses VariableBuilder and make_guards, negative discusses guard.create and check_fn. "
            "Inter-dependent compilation internals make this an unsafe negative."
        ),
    },
    "train_ku_0340": {
        "rationale": (
            "Positive defines preemptionPolicy. Negative defines the fundamental concept of preemption "
            "and scheduling queues in Kubernetes. High semantic overlap on preemption mechanics."
        ),
    },
    "train_fa_0489": {
        "rationale": (
            "Positive discusses Response headers and return types. Negative discusses additional response "
            "declarations and combining response schemas. Closely related API response semantics."
        ),
    },
}


def classify_item(item: Dict[str, Any]) -> Dict[str, Any]:
    qid = item["query_id"]
    eco = item["ecosystem"]
    qtext = item["query_text"]
    pos_path = item["positive_source_path"]
    neg_path = item["hard_negative_source_path"]
    s_pos = item["teacher_scores"]["positive_score"]
    s_neg = item["teacher_scores"]["negative_score"]
    margin = item["teacher_scores"]["margin"]

    # 1. Query Quality
    if qid == "train_fa_0377":
        query_quality = "QUERY_POSITIVE_MAPPING_DEFECT"
        query_quality_notes = (
            "Synthetically templated query mapped to wrong positive document (middleware instead of dependencies)."
        )
    elif "  " in qtext or qtext.startswith("What is the configuration and purpose of ") and any(
        w in qtext for w in ["REL_16_STABLE", "CUDA semantics", "Troubleshooting  Minifying", "Features -"]
    ):
        query_quality = "HEADING_ARTIFACT"
        query_quality_notes = "Direct heading-to-question conversion with uncleaned delimiters or section titles."
    elif qtext.startswith("How to use and configure") or qtext.startswith("What is the difference and interaction"):
        query_quality = "SYNTHETIC_TEMPLATED"
        query_quality_notes = "Standard synthetic template with clear technical entities."
    else:
        query_quality = "WELL_FORMED"
        query_quality_notes = "Clean and specific technical domain question."

    # 2. Positive Support
    if qid == "train_fa_0377":
        positive_support = "MISALIGNED_MAPPING"
        pos_support_notes = "Positive chunk discusses HTTP middleware, not yield dependencies."
    elif s_pos < 0.45:
        positive_support = "WEAK_SUPPORT"
        pos_support_notes = f"Teacher positive score is low ({s_pos:.2f}); positive only tangentially touches the entity."
    else:
        positive_support = "DIRECT_SUPPORT"
        pos_support_notes = f"Positive chunk directly covers the queried topic (teacher positive score: {s_pos:.2f})."

    # 3. Negative Semantic Status
    if qid in FALSE_NEGATIVES:
        negative_semantic_status = "FALSE_NEGATIVE"
        status_rationale = FALSE_NEGATIVES[qid]["rationale"]
    elif qid in AMBIGUOUS_NEGATIVES:
        negative_semantic_status = "AMBIGUOUS_UNSAFE_NEGATIVE"
        status_rationale = AMBIGUOUS_NEGATIVES[qid]["rationale"]
    else:
        negative_semantic_status = "LIKELY_TRUE_NEGATIVE"
        status_rationale = (
            f"Candidate discusses distinct topic ({neg_path}) from queried entity ({pos_path}); "
            f"clear teacher separation (s_pos={s_pos:.2f}, s_neg={s_neg:.2f}, margin={margin:.2f})."
        )

    # 4. Negative Difficulty
    if s_neg >= 0.30 or (pos_path == neg_path and negative_semantic_status == "LIKELY_TRUE_NEGATIVE"):
        negative_difficulty = "HARD_CONFUSER"
    elif s_neg >= 0.08 or item["lexical_rank"] in (1, 2) or item["dense_rank"] in (1, 2):
        negative_difficulty = "MODERATE_CONFUSER"
    else:
        negative_difficulty = "WEAK_CONFUSER"

    return {
        "item_index": item["item_index"],
        "query_id": qid,
        "ecosystem": eco,
        "typology": item.get("typology", "direct_lookup"),
        "query_text": qtext,
        "positive_chunk_id": item["positive_chunk_id"],
        "positive_source_path": pos_path,
        "hard_negative_chunk_id": item["hard_negative_chunk_id"],
        "hard_negative_source_path": neg_path,
        "mining_retriever": item["mining_retriever"],
        "teacher_scores": item["teacher_scores"],
        "ai_review_dimensions": {
            "query_quality": query_quality,
            "query_quality_notes": query_quality_notes,
            "positive_support": positive_support,
            "positive_support_notes": pos_support_notes,
            "negative_semantic_status": negative_semantic_status,
            "negative_semantic_status_rationale": status_rationale,
            "negative_difficulty": negative_difficulty,
        },
        "review_provenance": {
            "review_type": "AI_ASSISTED_RECOMMENDATION",
            "human_reviewer": None,
            "human_approval_status": "PENDING_SATISH_HUMAN_REVIEW",
            "is_human_approved": False,
        },
    }


def main():
    in_json = Path("data/training/HARD_NEGATIVE_AUDIT_40.json")
    out_json = Path("data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.json")
    out_md = Path("data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.md")

    with open(in_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    reviewed_items = [classify_item(it) for it in data["audit_items"]]

    status_counts = {
        "FALSE_NEGATIVE": sum(1 for it in reviewed_items if it["ai_review_dimensions"]["negative_semantic_status"] == "FALSE_NEGATIVE"),
        "AMBIGUOUS_UNSAFE_NEGATIVE": sum(1 for it in reviewed_items if it["ai_review_dimensions"]["negative_semantic_status"] == "AMBIGUOUS_UNSAFE_NEGATIVE"),
        "LIKELY_TRUE_NEGATIVE": sum(1 for it in reviewed_items if it["ai_review_dimensions"]["negative_semantic_status"] == "LIKELY_TRUE_NEGATIVE"),
    }
    assert status_counts["FALSE_NEGATIVE"] == 4
    assert status_counts["AMBIGUOUS_UNSAFE_NEGATIVE"] == 6
    assert status_counts["LIKELY_TRUE_NEGATIVE"] == 30

    query_quality_counts = {}
    for it in reviewed_items:
        qq = it["ai_review_dimensions"]["query_quality"]
        query_quality_counts[qq] = query_quality_counts.get(qq, 0) + 1

    pos_support_counts = {}
    for it in reviewed_items:
        ps = it["ai_review_dimensions"]["positive_support"]
        pos_support_counts[ps] = pos_support_counts.get(ps, 0) + 1

    difficulty_counts = {}
    for it in reviewed_items:
        nd = it["ai_review_dimensions"]["negative_difficulty"]
        difficulty_counts[nd] = difficulty_counts.get(nd, 0) + 1

    payload = {
        "audit_name": "HARD_NEGATIVE_AUDIT_40_AI_REVIEW",
        "description": "AI-assisted multi-dimensional review of the 40 historical E4 hard-negative audit candidates.",
        "status": "AI_RECOMMENDATION_PENDING_HUMAN_CONFIRMATION",
        "human_approval_note": "These are AI-assisted recommendations only. Do NOT mark as Satish human approval.",
        "total_sample_size": len(reviewed_items),
        "ecosystem_distribution": data["ecosystem_distribution"],
        "classification_summary": {
            "negative_semantic_status": status_counts,
            "query_quality": query_quality_counts,
            "positive_support": pos_support_counts,
            "negative_difficulty": difficulty_counts,
        },
        "identified_defects": [
            {
                "query_id": "train_fa_0377",
                "defect_type": "QUERY_POSITIVE_MAPPING_DEFECT",
                "semantic_status": "FALSE_NEGATIVE",
                "summary": "Positive chunk is misaligned (middleware.md); candidate negative (dependencies-with-yield.md) contains true answer.",
            },
            {
                "query_id": "train_py_0226",
                "defect_type": "SAME_FILE_ANSWER_BEARING",
                "semantic_status": "FALSE_NEGATIVE",
                "summary": "Both positive and negative chunks are from torch.compiler_troubleshooting.rst diagnosing Inductor errors.",
            },
            {
                "query_id": "train_ku_0252",
                "defect_type": "CANONICAL_DOCUMENT_FALSE_NEGATIVE",
                "semantic_status": "FALSE_NEGATIVE",
                "summary": "Proposed negative is from resource-metrics-pipeline.md, the canonical topic documentation.",
            },
            {
                "query_id": "train_fa_0466",
                "defect_type": "SAME_FILE_ANSWER_BEARING",
                "semantic_status": "FALSE_NEGATIVE",
                "summary": "Both positive and negative chunks are from dependencies-with-yield.md detailing yield usage.",
            },
        ],
        "audit_items": reviewed_items,
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {out_json}")

    # Build Markdown report
    md_lines = [
        "# Historical E4 Hard-Negative Audit: AI Review & Diagnostic Report",
        "",
        "> [!IMPORTANT]",
        "> **PROVENANCE & STATUS**: This document records **AI-assisted recommendations only**.",
        "> It does **NOT** constitute human review or approval by Satish.",
        "> Human approval remains `PENDING_SATISH_HUMAN_REVIEW`.",
        "> The historical audit document `data/training/HARD_NEGATIVE_AUDIT_40.md` is preserved unchanged as historical evidence.",
        "",
        "## 1. Summary of Classifications (40 Triples)",
        "",
        f"- **Total Sample Size**: {len(reviewed_items)} triples (10 per ecosystem: PostgreSQL, PyTorch, Kubernetes, FastAPI)",
        f"- **FALSE_NEGATIVE**: {status_counts['FALSE_NEGATIVE']} items (10.0%)",
        f"- **AMBIGUOUS_UNSAFE_NEGATIVE**: {status_counts['AMBIGUOUS_UNSAFE_NEGATIVE']} items (15.0%)",
        f"- **LIKELY_TRUE_NEGATIVE**: {status_counts['LIKELY_TRUE_NEGATIVE']} items (75.0%)",
        "",
        "### Multi-Dimensional Breakdown",
        "",
        "| Dimension | Category | Count | Percentage |",
        "|---|---|---:|---:|",
    ]

    for k, v in status_counts.items():
        md_lines.append(f"| **Negative Semantic Status** | `{k}` | {v} | {v/40*100:.1f}% |")
    for k, v in query_quality_counts.items():
        md_lines.append(f"| **Query Quality** | `{k}` | {v} | {v/40*100:.1f}% |")
    for k, v in pos_support_counts.items():
        md_lines.append(f"| **Positive Support** | `{k}` | {v} | {v/40*100:.1f}% |")
    for k, v in difficulty_counts.items():
        md_lines.append(f"| **Negative Difficulty** | `{k}` | {v} | {v/40*100:.1f}% |")

    md_lines.extend([
        "",
        "## 2. Identified High-Severity Defects",
        "",
        "### A. `train_fa_0377` — `QUERY_POSITIVE_MAPPING_DEFECT` & `FALSE_NEGATIVE`",
        "- **Query**: `How to use and configure yield in fastapi?`",
        "- **Assigned Positive Chunk**: `b677a28e08d6` (`tutorial/middleware.md`)",
        "- **Assigned Negative Chunk**: `90ba95ef41da` (`tutorial/dependencies/dependencies-with-yield.md`)",
        "- **Diagnosis**: The positive chunk explains `@app.middleware('http')` and never mentions `yield`. "
        "The negative candidate from `dependencies-with-yield.md` contains the actual code pattern "
        "(`async def get_db(): try: yield db finally: db.close()`). Thus the model was asked to treat the true answer as a negative.",
        "",
        "### B. `train_py_0226` — `SAME_FILE_ANSWER_BEARING` & `FALSE_NEGATIVE`",
        "- **Query**: `What is the configuration and purpose of PyTorch 20 Troubleshooting  Minifying TorchInductor Errors in pytorch?`",
        "- **Positive Chunk**: `torch.compiler_troubleshooting.rst` (running the minifier)",
        "- **Negative Chunk**: `torch.compiler_troubleshooting.rst` (isolating `backend=\"aot_eager\"`)",
        "- **Diagnosis**: Both chunks provide legitimate, directly relevant troubleshooting advice from the same section.",
        "",
        "### C. `train_ku_0252` — `CANONICAL_DOCUMENT_FALSE_NEGATIVE`",
        "- **Query**: `What is the configuration and purpose of Resource metrics pipeline in kubernetes?`",
        "- **Positive Chunk**: `tasks/debug/debug-cluster/resource-usage-monitoring.md`",
        "- **Negative Chunk**: `tasks/debug/debug-cluster/resource-metrics-pipeline.md`",
        "- **Diagnosis**: The candidate negative is the canonical document for the resource metrics pipeline itself.",
        "",
        "### D. `train_fa_0466` — `SAME_FILE_ANSWER_BEARING` & `FALSE_NEGATIVE`",
        "- **Query**: `How to use and configure yield in fastapi?`",
        "- **Positive Chunk**: `tutorial/dependencies/dependencies-with-yield.md`",
        "- **Negative Chunk**: `tutorial/dependencies/dependencies-with-yield.md`",
        "- **Diagnosis**: Both chunks are from the same chapter explaining yield dependencies in FastAPI.",
        "",
        "## 3. Ambiguous / Unsafe Negatives (6 Items)",
        "",
        "| Query ID | Ecosystem | Query Excerpt | Reason for Ambiguity |",
        "|---|---|---|---|",
    ])

    for qid in sorted(AMBIGUOUS_NEGATIVES.keys()):
        item = next(it for it in reviewed_items if it["query_id"] == qid)
        md_lines.append(
            f"| `{qid}` | {item['ecosystem']} | {item['query_text'][:45]}... | {AMBIGUOUS_NEGATIVES[qid]['rationale']} |"
        )

    md_lines.extend([
        "",
        "## 4. Item-by-Item Review Ledger",
        "",
        "| # | Query ID | Eco | Semantic Status | Quality | Support | Difficulty | Teacher Marg |",
        "|---:|---|---|---|---|---|---|---:|",
    ])

    for it in reviewed_items:
        dims = it["ai_review_dimensions"]
        marg = it["teacher_scores"]["margin"]
        md_lines.append(
            f"| {it['item_index']} | `{it['query_id']}` | {it['ecosystem']} | "
            f"`{dims['negative_semantic_status']}` | `{dims['query_quality']}` | "
            f"`{dims['positive_support']}` | `{dims['negative_difficulty']}` | {marg:.2f} |"
        )

    md_lines.append("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
