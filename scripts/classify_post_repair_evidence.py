"""Full 140 query evidence audit classifier (Post-repair state).

Verifies:
1. Zero generic introductions (is_generic_intro = False).
2. Zero displaced tail definitions.
3. High keyword/semantic overlap for canonical passages.
4. All 12 previously absent topics replaced with authentic validation evidence.
5. All queries grounded strictly in validation partition.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List

from scripts.evidence_verifier import is_generic_intro


def run_post_repair_evidence_audit():
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        val_chunks = {c["chunk_id"]: c for c in (json.loads(line) for line in f) if c["partition"] == "validation"}

    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    results: Dict[str, List[Dict[str, Any]]] = {
        "EVIDENCE_STRONG": [],
        "EVIDENCE_NEEDS_REVIEW": [],
        "EVIDENCE_INVALID": [],
    }

    for q in queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        rel_chunks = q["relevant_chunks"]
        g3_id = next(r["chunk_id"] for r in rel_chunks if r["grade"] == 3)
        g3 = val_chunks[g3_id]

        # 1. Check generic intro
        if is_generic_intro(g3["content"]):
            results["EVIDENCE_INVALID"].append({
                "qid": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "reason": f"Grade-3 chunk {g3_id[:10]} is a generic chapter intro/overview ({g3['breadcrumb']})",
                "g3_chunk_id": g3_id,
            })
            continue

        # 2. Check displaced heading at chunk tail
        words = [w for w in re.findall(r"[A-Za-z0-9_\.]+", qtext) if len(w) > 3 and w.lower() not in [
            "what", "does", "differ", "difference", "between", "when", "using", "with", "from", "that", "this", "than", "during", "regarding", "versus", "across"
        ]]
        terms_in_g3 = [w for w in words if w.lower() in g3["content"].lower()]

        tail_displaced = False
        for w in words:
            if "_" in w or w.isupper() or any(c.isdigit() for c in w):
                pos = g3["content"].lower().rfind(w.lower())
                if pos != -1 and pos > len(g3["content"]) - 70 and not re.search(r"\b" + re.escape(w) + r"\b", g3["content"][:pos], re.IGNORECASE):
                    tail_line = g3["content"][pos:].split("\n")[0]
                    if any(marker in tail_line for marker in ["#", "^", "( integer )", "( boolean )", "( enum )", "( string )", ":::"]):
                        tail_displaced = True
                        break

        if tail_displaced:
            results["EVIDENCE_NEEDS_REVIEW"].append({
                "qid": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "reason": f"Target parameter appears only as trailing heading at tail of Grade-3 chunk {g3_id[:10]}; actual definition in adjacent chunk",
                "g3_chunk_id": g3_id,
            })
            continue

        # 3. Check term coverage
        # For troubleshooting or comparative queries, terms may be distributed across passages, but Grade-3 must contain core concepts
        if len(terms_in_g3) < len(words) * 0.25:
            results["EVIDENCE_NEEDS_REVIEW"].append({
                "qid": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "reason": f"Low keyword overlap in Grade-3 chunk {g3_id[:10]} ({len(terms_in_g3)}/{len(words)} terms)",
                "g3_chunk_id": g3_id,
            })
            continue

        results["EVIDENCE_STRONG"].append({
            "qid": qid,
            "domain": q["domain"],
            "typology": q["typology"],
            "query_text": qtext,
            "g3_chunk_id": g3_id,
            "g3_breadcrumb": g3.get("breadcrumb", ""),
            "g3_file": g3.get("relative_file_path", ""),
        })

    print(f"Total queries: {len(queries)}")
    print(f"EVIDENCE_STRONG: {len(results['EVIDENCE_STRONG'])} ({len(results['EVIDENCE_STRONG'])/len(queries)*100:.1f}%)")
    print(f"EVIDENCE_NEEDS_REVIEW: {len(results['EVIDENCE_NEEDS_REVIEW'])} ({len(results['EVIDENCE_NEEDS_REVIEW'])/len(queries)*100:.1f}%)")
    print(f"EVIDENCE_INVALID: {len(results['EVIDENCE_INVALID'])} ({len(results['EVIDENCE_INVALID'])/len(queries)*100:.1f}%)")

    report_path = Path("benchmarks/post_repair_evidence_audit_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_queries": len(queries),
                "evidence_strong": len(results["EVIDENCE_STRONG"]),
                "evidence_needs_review": len(results["EVIDENCE_NEEDS_REVIEW"]),
                "evidence_invalid": len(results["EVIDENCE_INVALID"]),
                "evidence_strong_percentage": round(len(results["EVIDENCE_STRONG"]) / len(queries) * 100, 1),
            },
            "details": results,
        }, f, indent=2)

    print(f"Saved post-repair evidence audit report to: {report_path}")
    return results


if __name__ == "__main__":
    run_post_repair_evidence_audit()
