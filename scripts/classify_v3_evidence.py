"""Automated Evidence Sanity Audit Classifier for Benchmark v0 (V3 State).

Evaluates all 140 development benchmark queries against structural sanity checks:
1. Zero generic introductions (is_generic_intro = False) -> FAIL if detected.
2. Zero displaced tail definitions -> REVIEW if detected.
3. Keyword/semantic overlap for canonical passages.
4. Output classifications: AUTOMATED_CHECK_PASS, AUTOMATED_CHECK_REVIEW, AUTOMATED_CHECK_FAIL.
Saves report to benchmarks/v3_evidence_audit_report.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List

from scripts.evidence_verifier import is_generic_intro


def run_v3_evidence_audit() -> Dict[str, Any]:
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        val_chunks = {c["chunk_id"]: c for c in (json.loads(line) for line in f) if c["partition"] == "validation"}

    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    results: Dict[str, List[Dict[str, Any]]] = {
        "AUTOMATED_CHECK_PASS": [],
        "AUTOMATED_CHECK_REVIEW": [],
        "AUTOMATED_CHECK_FAIL": [],
    }

    for q in queries:
        qid = q["query_id"]
        qtext = q["query_text"]
        rel_chunks = q["relevant_chunks"]
        g3_id = next(r["chunk_id"] for r in rel_chunks if r["grade"] == 3)
        g3 = val_chunks[g3_id]

        # 1. Check generic intro
        if is_generic_intro(g3["content"]):
            results["AUTOMATED_CHECK_FAIL"].append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "reason": f"Grade-3 chunk {g3_id[:10]} is a generic chapter intro/overview ({g3.get('breadcrumb', '')})",
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
            results["AUTOMATED_CHECK_REVIEW"].append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "reason": f"Target parameter appears only as trailing heading at tail of Grade-3 chunk {g3_id[:10]}; actual definition in adjacent chunk",
                "g3_chunk_id": g3_id,
            })
            continue

        # 3. Check term coverage
        if len(terms_in_g3) < len(words) * 0.25:
            results["AUTOMATED_CHECK_REVIEW"].append({
                "query_id": qid,
                "domain": q["domain"],
                "typology": q["typology"],
                "query_text": qtext,
                "reason": f"Low keyword overlap in Grade-3 chunk {g3_id[:10]} ({len(terms_in_g3)}/{len(words)} terms)",
                "g3_chunk_id": g3_id,
            })
            continue

        results["AUTOMATED_CHECK_PASS"].append({
            "query_id": qid,
            "domain": q["domain"],
            "typology": q["typology"],
            "query_text": qtext,
            "g3_chunk_id": g3_id,
            "g3_breadcrumb": g3.get("breadcrumb", ""),
            "g3_file": g3.get("relative_file_path", ""),
        })

    report = {
        "summary": {
            "total_queries": len(queries),
            "automated_check_pass": len(results["AUTOMATED_CHECK_PASS"]),
            "automated_check_review": len(results["AUTOMATED_CHECK_REVIEW"]),
            "automated_check_fail": len(results["AUTOMATED_CHECK_FAIL"]),
            "pass_percentage": round(len(results["AUTOMATED_CHECK_PASS"]) / len(queries) * 100, 1),
        },
        "details": results,
    }

    print(f"Total queries: {len(queries)}")
    print(f"AUTOMATED_CHECK_PASS: {report['summary']['automated_check_pass']} ({report['summary']['pass_percentage']}%)")
    print(f"AUTOMATED_CHECK_REVIEW: {report['summary']['automated_check_review']}")
    print(f"AUTOMATED_CHECK_FAIL: {report['summary']['automated_check_fail']}")

    report_path = Path("benchmarks/v3_evidence_audit_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Saved V3 evidence audit report to: {report_path}")
    return report


if __name__ == "__main__":
    run_v3_evidence_audit()
