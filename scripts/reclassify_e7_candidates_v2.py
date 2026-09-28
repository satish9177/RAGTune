"""Reclassify E7 candidates using multi-layer semantic-answer-overlap shields.

Implements:
- Entity extraction for query, positive, candidate.
- Answer-function classification (DEFINITION, CONFIGURATION, PROCEDURE, TROUBLESHOOTING, COMPARISON_SIDE, EXAMPLE, GENERAL_CONTEXT, NAVIGATION_ONLY).
- Semantic shields:
  1. Strict same-document quarantine.
  2. Comparative query partial/both-side answer quarantine.
  3. Query entity match + explanatory/action language quarantine.
  4. Troubleshooting query resolution/error-handling quarantine.
  5. Teacher cross-encoder margin & score thresholds.
  6. Hardness & triviality screening (REJECT_TOO_EASY).

Outputs:
- data/training/e7_candidate_ledger_v2.jsonl
- data/training/e7_safe_negatives_v2.jsonl
- data/training/e7_candidate_disposition_v2.json
- data/training/E7_NEGATIVE_AUDIT_40_V2.json
- data/training/E7_NEGATIVE_AUDIT_40_V2.md
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple


def truncate_text(text: str, max_chars: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "..."


def extract_entities(text: str) -> Set[str]:
    """Extract normalized technical entities from text."""
    entities = set()

    # 1. Backticked terms
    for m in re.findall(r"`([^`]+)`", text):
        clean = m.strip().strip("'\"")
        if len(clean) >= 2 and not clean.startswith("http"):
            entities.add(clean.lower())

    # 2. Dotted terms (e.g. spec.replicas, torch.distributed, get_db.close)
    for m in re.findall(r"\b[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\b", text):
        entities.add(m.lower())

    # 3. Snake_case terms (e.g. get_current_user, priority_class_name, lo_read)
    for m in re.findall(r"\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b", text):
        entities.add(m.lower())

    # 4. CamelCase or PascalCase terms (e.g. PriorityClass, AdmissionReview, UserIn)
    for m in re.findall(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b", text):
        entities.add(m.lower())

    # 5. ALL_CAPS constants or env vars (e.g. TORCH_DISTRIBUTED_DEBUG, REL_16_STABLE)
    for m in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text):
        if m not in {"WHAT", "HOW", "THE", "AND", "FOR", "WITH", "WHEN", "WHERE"}:
            entities.add(m.lower())

    # 6. Specific framework keywords and fields
    for m in re.findall(
        r"\b(dict|list|response|header|cookie|token|auth|session|transaction|subscription|preemption|admission|scheduler|replicas|workload|executor|tensor|autograd)\b",
        text,
        re.IGNORECASE,
    ):
        entities.add(m.lower())

    return entities


def extract_query_entities(qtext: str, typology: str) -> Tuple[Set[str], List[str]]:
    """Extract substantive target entities from query, handling comparative structures."""
    entities = extract_entities(qtext)

    # Clean generic template noise
    noise = {
        "difference", "interaction", "between", "how", "use", "configure", "resolve",
        "issues", "error", "warning", "purpose", "configuration", "postgresql",
        "pytorch", "kubernetes", "fastapi"
    }
    cleaned_entities = {e for e in entities if e not in noise and len(e) > 2}

    comparative_sides = []
    if typology == "comparative_discrimination" or "difference and interaction between" in qtext.lower():
        m = re.search(r"between\s+(.+?)\s+and\s+(.+?)(?:\s+in\s+|\?$|$)", qtext, re.IGNORECASE)
        if m:
            side1 = m.group(1).strip().strip("`'\"").lower()
            side2 = m.group(2).strip().strip("`'\"").lower()
            comparative_sides = [side1, side2]
            cleaned_entities.add(side1)
            cleaned_entities.add(side2)

    return cleaned_entities, comparative_sides


def classify_answer_functions(text: str) -> Set[str]:
    """Classify candidate text into functional answer roles."""
    functions = set()
    text_lower = text.lower()

    # CONFIGURATION
    if any(k in text_lower for k in [
        "spec:", "metadata:", "apiversion:", "yaml", "config", "setting", "parameter",
        "default:", "optional", "flag", "--", "conf", "postgresql.conf", "environ[",
        "dependency", "depends", "scope", "scopes", "header", "cookie", "field"
    ]):
        functions.add("CONFIGURATION")

    # PROCEDURE
    if any(k in text_lower for k in [
        "how to", "step", "install", "deploy", "run", "curl", "kubectl", "pip install",
        "python -m", "tar xf", "make install", "create a", "add the following", "def "
    ]):
        functions.add("PROCEDURE")

    # TROUBLESHOOTING
    if any(k in text_lower for k in [
        "error", "exception", "warning", "fail", "timeout", "oom", "debug", "troubleshoot",
        "fix", "resolve", "crash", "skip", "violate", "constraint", "repro", "traceback"
    ]):
        functions.add("TROUBLESHOOTING")

    # DEFINITION
    if any(k in text_lower for k in [
        "is a", "refers to", "defined as", "represents", "meaning", "overview", "provides", "features", "data types"
    ]):
        functions.add("DEFINITION")

    # EXAMPLE
    if "```" in text or "example:" in text_lower or "for example" in text_lower:
        functions.add("EXAMPLE")

    # NAVIGATION_ONLY
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) > 4 and sum(len(l) < 60 for l in lines[:5]) >= 4:
        if any(k in text_lower for k in ["see also", "table of contents", "contents:", "next steps", "index:"]):
            functions.add("NAVIGATION_ONLY")

    if not functions:
        functions.add("GENERAL_CONTEXT")

    return functions


def evaluate_candidate_v2(
    cand: Dict[str, Any],
    pos_chunk: Dict[str, Any],
    neg_chunk: Dict[str, Any],
    q_spec: Dict[str, Any],
) -> Tuple[str, str, Dict[str, Any]]:
    qid = cand["query_id"]
    qtext = q_spec["query_text"]
    typology = q_spec.get("typology", "direct_lookup")

    pos_id = q_spec["positive_chunk_id"]
    neg_id = cand["candidate_chunk_id"]

    pos_path = pos_chunk.get("relative_file_path", "")
    neg_path = neg_chunk.get("relative_file_path", "")

    pos_text = pos_chunk.get("content", "")
    neg_text = neg_chunk.get("content", "")
    neg_lower = neg_text.lower()

    s_pos = cand["positive_teacher_score"]
    s_neg = cand["candidate_teacher_score"]
    margin = cand["teacher_margin"]

    # Entities
    q_entities, comp_sides = extract_query_entities(qtext, typology)
    neg_entities = extract_entities(neg_text)
    pos_entities = extract_entities(pos_text)
    entity_overlap = q_entities & neg_entities

    # Answer functions
    answer_functions = classify_answer_functions(neg_text)

    # Hardness signals
    hybrid_rank = cand.get("hybrid_rank")
    lexical_rank = cand.get("lexical_rank")
    dense_rank = cand.get("dense_rank")

    has_top10_rank = (
        (hybrid_rank is not None and hybrid_rank <= 10) or
        (lexical_rank is not None and lexical_rank <= 10) or
        (dense_rank is not None and dense_rank <= 10)
    )

    meta = {
        "query_entities": sorted(list(q_entities)),
        "positive_entities": sorted(list(pos_entities)),
        "candidate_entities": sorted(list(neg_entities)),
        "entity_overlap": sorted(list(entity_overlap)),
        "comparative_sides": comp_sides,
        "answer_functions": sorted(list(answer_functions)),
        "hardness_signal": {
            "has_top10_rank": has_top10_rank,
            "hybrid_rank": hybrid_rank,
            "lexical_rank": lexical_rank,
            "dense_rank": dense_rank,
            "teacher_negative_score": s_neg,
        }
    }

    # 1. Known Positive Exclusion
    if pos_id == neg_id:
        return "REJECT_KNOWN_RELEVANT", "MATCHES_KNOWN_GROUND_TRUTH_POSITIVE", meta

    # 2. Strict Same-Document Quarantine
    # In technical documentation, different sections of the same file address related mechanisms
    if pos_path and neg_path and pos_path == neg_path:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "SAME_DOCUMENT_CONTEXT_LEAK", meta

    # 2b. High Lexical Overlap Shield
    jaccard = cand.get("lexical_overlap_jaccard", 0.0)
    if jaccard is not None and jaccard > 0.40:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "HIGH_LEXICAL_OVERLAP_WITH_POSITIVE", meta

    # 2c. Require Valid Teacher Cross-Encoder Scoring
    if s_neg is None or s_pos is None or margin is None:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "UNSCORED_TEACHER_CANDIDATE", meta

    # 3. Comparative Query Partial / Both-Side Answer Shield (Rule B)
    if comp_sides:
        # Candidate covers both sides
        if all(len(side) >= 3 and side in neg_lower for side in comp_sides):
            meta["answer_functions"].append("COMPARISON_SIDE")
            return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "COMPARATIVE_QUERY_COVERS_BOTH_SIDES", meta

        # Candidate covers either side
        for side in comp_sides:
            if len(side) >= 3 and side in neg_lower:
                meta["answer_functions"].append("COMPARISON_SIDE")
                return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", f"COMPARATIVE_QUERY_PARTIAL_ANSWER_FOR_{side.upper()}", meta

    # 4. Exact Technical Entity Match + Explanatory/Action Language (Rule A)
    explanatory_action_words = {
        "setting", "behavior", "default", "yaml", "config", "configuration", "parameter", "option",
        "dependency", "sub-dependency", "scope", "scopes", "function", "method", "class", "syntax",
        "declare", "declared", "pass", "passed", "return", "returns", "call", "using", "usage",
        "spec", "field", "error", "exception", "handler", "handling", "workaround", "fix",
        "install", "deploy", "setup", "run", "restarts", "repro", "traceback"
    }

    for qe in q_entities:
        if len(qe) >= 4 and qe in neg_lower:
            if any(w in neg_lower for w in explanatory_action_words) or any(
                fn in answer_functions for fn in ["CONFIGURATION", "PROCEDURE", "TROUBLESHOOTING", "DEFINITION", "EXAMPLE"]
            ):
                return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", f"ENTITY_MATCH_WITH_ACTION_LANGUAGE_{qe.upper()}", meta

    # 5. Troubleshooting Query Resolution / Diagnostics (Rule C)
    if typology == "troubleshooting_scenario" or "how to resolve" in qtext.lower() or "troubleshoot" in qtext.lower():
        if any(qe in neg_lower for qe in q_entities) or "TROUBLESHOOTING" in answer_functions:
            return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "TROUBLESHOOTING_RESOLUTION_OR_ERROR_HANDLING", meta

    # 6. Teacher Cross-Encoder Safeguards (Teacher as safety filter, not sole certification)
    if margin is not None and margin <= 0.0:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "TEACHER_INVERSION_OR_TIE", meta
    if s_neg is not None and s_neg >= 0.60:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "HIGH_TEACHER_SCORE_PROBABLE_ANSWER", meta
    if margin is not None and margin < 0.25:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "AMBIGUOUS_TEACHER_MARGIN", meta
    if s_pos is not None and s_pos < 0.30:
        return "QUARANTINE_POSSIBLE_FALSE_NEGATIVE", "LOW_POSITIVE_TEACHER_CONFIDENCE", meta

    # 7. Candidate Hardness Screening (Requirement 7)
    if s_neg is not None and s_neg < 0.02:
        return "REJECT_TOO_EASY", "NEGLIGIBLE_TEACHER_SCORE_TRIVIAL_NEGATIVE", meta
    if "NAVIGATION_ONLY" in answer_functions:
        return "REJECT_TOO_EASY", "NAVIGATION_OR_INDEX_PASSAGE", meta
    if not has_top10_rank and (s_neg is not None and s_neg < 0.05):
        return "REJECT_TOO_EASY", "LOW_RANK_AND_LOW_SIMILARITY", meta

    # Certified SAFE_NEGATIVE_V2
    return "SAFE_NEGATIVE_V2", "VERIFIED_HARD_CONFUSER_DIFFERENT_ANSWER", meta


def main():
    print("=" * 80)
    print("E7 CANDIDATE RECLASSIFICATION V2 (Multi-Signal Semantic Shields)")
    print("=" * 80)

    ledger_v1_path = Path("data/training/e7_candidate_ledger.jsonl")
    manifest_path = Path("data/training/E7_PRIMARY_QUERY_MANIFEST.json")
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")

    out_ledger_v2 = Path("data/training/e7_candidate_ledger_v2.jsonl")
    out_safe_v2 = Path("data/training/e7_safe_negatives_v2.jsonl")
    out_disp_v2 = Path("data/training/e7_candidate_disposition_v2.json")
    out_audit_json = Path("data/training/E7_NEGATIVE_AUDIT_40_V2.json")
    out_audit_md = Path("data/training/E7_NEGATIVE_AUDIT_40_V2.md")

    # Load 188 queries
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    query_lookup = {q["query_id"]: q for q in manifest["queries"]}

    # Load chunk contents
    print("Loading train chunk contents...")
    chunk_by_id = {}
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                if c["partition"] == "train":
                    chunk_by_id[c["chunk_id"]] = c

    # Load ledger v1
    print("Loading candidate ledger v1...")
    with open(ledger_v1_path, "r", encoding="utf-8") as f:
        ledger_v1 = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(ledger_v1)} candidates from V1 ledger.")

    # Reclassify all candidates
    ledger_v2: List[Dict[str, Any]] = []
    v1_to_v2_transitions: Dict[Tuple[str, str], int] = {}
    disposition_counts_v2: Dict[str, int] = {
        "SAFE_NEGATIVE_V2": 0,
        "QUARANTINE_POSSIBLE_FALSE_NEGATIVE": 0,
        "REJECT_KNOWN_RELEVANT": 0,
        "REJECT_TOO_EASY": 0,
    }
    quarantine_reasons_v2: Dict[str, int] = {}

    for cand in ledger_v1:
        qid = cand["query_id"]
        q_spec = query_lookup[qid]
        pos_chunk = chunk_by_id[cand["positive_chunk_id"]]
        neg_chunk = chunk_by_id[cand["candidate_chunk_id"]]

        v1_disp = cand["classification"]
        v2_disp, v2_reason, meta = evaluate_candidate_v2(cand, pos_chunk, neg_chunk, q_spec)

        disposition_counts_v2[v2_disp] += 1
        trans_key = (v1_disp, v2_disp)
        v1_to_v2_transitions[trans_key] = v1_to_v2_transitions.get(trans_key, 0) + 1

        if v2_disp == "QUARANTINE_POSSIBLE_FALSE_NEGATIVE":
            quarantine_reasons_v2[v2_reason] = quarantine_reasons_v2.get(v2_reason, 0) + 1

        cand_v2 = dict(cand)
        cand_v2["classification_v1"] = v1_disp
        cand_v2["classification_reason_v1"] = cand["classification_reason"]
        cand_v2["classification_v2"] = v2_disp
        cand_v2["classification_reason_v2"] = v2_reason
        cand_v2["query_entities"] = meta["query_entities"]
        cand_v2["positive_entities"] = meta["positive_entities"]
        cand_v2["candidate_entities"] = meta["candidate_entities"]
        cand_v2["entity_overlap"] = meta["entity_overlap"]
        cand_v2["answer_functions"] = meta["answer_functions"]
        cand_v2["hardness_signal"] = meta["hardness_signal"]

        ledger_v2.append(cand_v2)

    assert len(ledger_v2) == len(ledger_v1) == 3760

    # Persist V2 ledger
    print(f"Writing V2 candidate ledger to {out_ledger_v2}...")
    with open(out_ledger_v2, "w", encoding="utf-8") as f:
        for item in ledger_v2:
            f.write(json.dumps(item) + "\n")

    # Extract SAFE_NEGATIVE_V2 pool
    safe_negatives_v2 = [item for item in ledger_v2 if item["classification_v2"] == "SAFE_NEGATIVE_V2"]
    print(f"Total SAFE_NEGATIVE_V2 candidates: {len(safe_negatives_v2)}")

    with open(out_safe_v2, "w", encoding="utf-8") as f:
        for item in safe_negatives_v2:
            f.write(json.dumps(item) + "\n")

    # Query coverage statistics
    queries_with_safe_neg = {item["query_id"] for item in safe_negatives_v2}
    total_queries = len(query_lookup)
    zero_safe_queries = sorted(list(set(query_lookup.keys()) - queries_with_safe_neg))

    neg_counts_per_query = [
        sum(1 for item in safe_negatives_v2 if item["query_id"] == qid)
        for qid in query_lookup.keys()
    ]
    median_neg = float(sorted(neg_counts_per_query)[len(neg_counts_per_query) // 2])
    max_neg = max(neg_counts_per_query) if neg_counts_per_query else 0

    safe_by_eco = {
        "postgresql": sum(1 for item in safe_negatives_v2 if item["domain"] == "postgresql"),
        "pytorch": sum(1 for item in safe_negatives_v2 if item["domain"] == "pytorch"),
        "kubernetes": sum(1 for item in safe_negatives_v2 if item["domain"] == "kubernetes"),
        "fastapi": sum(1 for item in safe_negatives_v2 if item["domain"] == "fastapi"),
    }

    # Transition report for SAFE_V1 candidates
    safe_v1_transitions = {
        "SAFE_V1_to_SAFE_V2": v1_to_v2_transitions.get(("SAFE_NEGATIVE", "SAFE_NEGATIVE_V2"), 0),
        "SAFE_V1_to_QUARANTINE": v1_to_v2_transitions.get(("SAFE_NEGATIVE", "QUARANTINE_POSSIBLE_FALSE_NEGATIVE"), 0),
        "SAFE_V1_to_RELEVANT": v1_to_v2_transitions.get(("SAFE_NEGATIVE", "REJECT_KNOWN_RELEVANT"), 0),
        "SAFE_V1_to_TOO_EASY": v1_to_v2_transitions.get(("SAFE_NEGATIVE", "REJECT_TOO_EASY"), 0),
    }

    print("\n" + "=" * 80)
    print("V1 -> V2 TRANSITION BREAKDOWN FOR HISTORICAL SAFE_NEGATIVE (1,216 items)")
    print("=" * 80)
    for k, v in safe_v1_transitions.items():
        pct = (v / 1216) * 100
        print(f"{k:35}: {v:5d} ({pct:5.2f}%)")
    print("=" * 80)

    print("\nV2 Disposition Counts (All 3,760 candidates):")
    for k, v in disposition_counts_v2.items():
        print(f"  {k:35}: {v:5d} ({v/3760*100:5.2f}%)")

    print(f"\nUnique queries covered by SAFE_NEGATIVE_V2: {len(queries_with_safe_neg)} / {total_queries}")
    print(f"Zero-safe-negative queries: {len(zero_safe_queries)}")
    print(f"Median negatives/query: {median_neg}")
    print(f"Max negatives/query: {max_neg}")
    print(f"Safe negatives by ecosystem: {safe_by_eco}")

    # Persist disposition payload
    disposition_payload = {
        "experiment": "E7_DOMAIN_RERANKER_RECLASSIFICATION_V2",
        "total_candidates": len(ledger_v2),
        "v2_disposition_counts": disposition_counts_v2,
        "safe_v1_transitions": safe_v1_transitions,
        "safe_negatives_v2_by_ecosystem": safe_by_eco,
        "query_coverage": {
            "total_queries": total_queries,
            "unique_queries_with_safe_negatives": len(queries_with_safe_neg),
            "zero_safe_negative_queries_count": len(zero_safe_queries),
            "zero_safe_negative_query_ids": zero_safe_queries,
            "median_negatives_per_query": median_neg,
            "max_negatives_per_query": max_neg,
        },
        "top_quarantine_reasons": dict(sorted(quarantine_reasons_v2.items(), key=lambda x: x[1], reverse=True)[:15]),
    }

    with open(out_disp_v2, "w", encoding="utf-8") as f:
        json.dump(disposition_payload, f, indent=2)

    # 8. Generate E7_NEGATIVE_AUDIT_40_V2 (Stratified Sample)
    print("\nGenerating E7_NEGATIVE_AUDIT_40_V2 stratified sample...")
    # Sort deterministically by hardness: hybrid_rank ascending, s_neg descending
    safe_negatives_v2.sort(key=lambda x: (x["domain"], x["hybrid_rank"] or 999, -(x["candidate_teacher_score"] if x["candidate_teacher_score"] is not None else -999.0)))

    audit_v2_items = []
    seen_audit_queries = set()

    # Stratified target per ecosystem: 10 per ecosystem, covering all available typologies
    for eco in ["postgresql", "pytorch", "kubernetes", "fastapi"]:
        eco_items = [e for e in safe_negatives_v2 if e["domain"] == eco]
        eco_selected = []

        # 1. Troubleshooting items (up to 2 if available)
        trouble_items = [e for e in eco_items if e["typology"] == "troubleshooting_scenario"]
        for it in trouble_items:
            if it["query_id"] not in seen_audit_queries:
                seen_audit_queries.add(it["query_id"])
                eco_selected.append(it)
                if len(eco_selected) >= 2:
                    break

        # 2. Comparative discrimination items (target 3-4 items)
        comp_items = [e for e in eco_items if e["typology"] == "comparative_discrimination"]
        for it in comp_items:
            if it["query_id"] not in seen_audit_queries:
                seen_audit_queries.add(it["query_id"])
                eco_selected.append(it)
                if len(eco_selected) >= 5:  # e.g. 2 trouble + 3 comp = 5
                    break

        # 3. Direct lookup items (fill up to 10)
        direct_items = [e for e in eco_items if e["typology"] == "direct_lookup"]
        for it in direct_items:
            if it["query_id"] not in seen_audit_queries:
                seen_audit_queries.add(it["query_id"])
                eco_selected.append(it)
                if len(eco_selected) >= 10:
                    break

        # 4. Fallback if still under 10
        if len(eco_selected) < 10:
            for it in eco_items:
                if it not in eco_selected:
                    eco_selected.append(it)
                    if len(eco_selected) >= 10:
                        break

        assert len(eco_selected) == 10, f"Expected 10 items for {eco}, got {len(eco_selected)}"
        audit_v2_items.extend(eco_selected)

    print(f"Sampled {len(audit_v2_items)} items for V2 human audit.")

    # Build E7_NEGATIVE_AUDIT_40_V2.json
    audit_json_items = []
    for idx, item in enumerate(audit_v2_items, start=1):
        q_spec = query_lookup[item["query_id"]]
        pos_chunk = chunk_by_id[item["positive_chunk_id"]]
        neg_chunk = chunk_by_id[item["candidate_chunk_id"]]

        pos_content = pos_chunk.get("content", "")
        neg_content = neg_chunk.get("content", "")

        audit_item = {
            "item_index": idx,
            "query_id": item["query_id"],
            "ecosystem": item["domain"],
            "typology": item["typology"],
            "query_text": q_spec["query_text"],
            "positive_chunk_id": item["positive_chunk_id"],
            "positive_source_path": item["positive_source_document"],
            "positive_excerpt": truncate_text(pos_content, 400),
            "hard_negative_chunk_id": item["candidate_chunk_id"],
            "hard_negative_source_path": item["source_document"],
            "hard_negative_excerpt": truncate_text(neg_content, 400),
            "mining_retriever": item["mining_retriever"],
            "lexical_rank": item["lexical_rank"],
            "dense_rank": item["dense_rank"],
            "hybrid_rank": item["hybrid_rank"],
            "rrf_score": item["rrf_score"],
            "teacher_scores": {
                "positive_score": item["positive_teacher_score"],
                "negative_score": item["candidate_teacher_score"],
                "margin": item["teacher_margin"],
            },
            "lexical_jaccard_overlap": item["lexical_overlap_jaccard"],
            "query_entities": item["query_entities"],
            "candidate_entities": item["candidate_entities"],
            "entity_overlap": item["entity_overlap"],
            "answer_functions": item["answer_functions"],
            "hardness_signal": item["hardness_signal"],
            "v2_verification_status": "SAFE_NEGATIVE_V2",
            "v2_verification_reason": item["classification_reason_v2"],
            "human_audit": {
                "decision": None,
                "allowed_decisions": ["TRUE_NEGATIVE", "FALSE_NEGATIVE", "AMBIGUOUS"],
                "difficulty_judgment": None,
                "allowed_difficulty_judgments": ["HARD_CONFUSER", "MODERATE_CONFUSER", "TRIVIAL"],
                "reviewer": None,
                "review_timestamp_utc": None,
                "reviewer_notes": "",
            },
        }
        audit_json_items.append(audit_item)

    v2_audit_payload = {
        "audit_name": "E7_NEGATIVE_AUDIT_40_V2",
        "description": "Regenerated E7 safe-negative human audit packet sampled strictly from SAFE_NEGATIVE_V2 pool under multi-layer semantic shields.",
        "status": "PENDING_HUMAN_AUDIT",
        "acceptance_gate": {
            "max_confirmed_false_negatives": 0,
            "max_ambiguous_rows": 2,
            "exclude_ambiguous_from_training": True,
            "min_difficulty_true_negatives": "MODERATE_CONFUSER",
        },
        "total_sample_size": len(audit_json_items),
        "ecosystem_distribution": {
            "postgresql": sum(1 for a in audit_json_items if a["ecosystem"] == "postgresql"),
            "pytorch": sum(1 for a in audit_json_items if a["ecosystem"] == "pytorch"),
            "kubernetes": sum(1 for a in audit_json_items if a["ecosystem"] == "kubernetes"),
            "fastapi": sum(1 for a in audit_json_items if a["ecosystem"] == "fastapi"),
        },
        "typology_distribution": {
            "direct_lookup": sum(1 for a in audit_json_items if a["typology"] == "direct_lookup"),
            "comparative_discrimination": sum(1 for a in audit_json_items if a["typology"] == "comparative_discrimination"),
            "troubleshooting_scenario": sum(1 for a in audit_json_items if a["typology"] == "troubleshooting_scenario"),
        },
        "audit_items": audit_json_items,
    }

    with open(out_audit_json, "w", encoding="utf-8") as f:
        json.dump(v2_audit_payload, f, indent=2)
    print(f"Generated {out_audit_json}")

    # Build E7_NEGATIVE_AUDIT_40_V2.md
    md_lines = [
        "# E7 Safe-Negative Human Verification Audit Packet V2 (40 Items)",
        "",
        "> [!IMPORTANT]",
        "> **AUDIT STATUS: `PENDING_HUMAN_AUDIT`**",
        "> This audit packet replaces the failed `E7_NEGATIVE_AUDIT_40` audit.",
        "> It is sampled strictly from the **`SAFE_NEGATIVE_V2`** candidate pool generated after applying:",
        "> 1. **Strict same-document quarantine** (zero same-file context leaks).",
        "> 2. **Comparative query partial/both-side answer shield** (no partial answers trained as negatives).",
        "> 3. **Entity-aware action/configuration shield** (quarantine on matching entity with config/procedure language).",
        "> 4. **Troubleshooting resolution shield** (quarantine on error handling / fix passages).",
        "> 5. **Non-circular teacher safeguards** (margin $\\ge 0.25$, $0.02 \\le s_{\\text{neg}} < 0.60$, $s_{\\text{pos}} \\ge 0.30$).",
        ">",
        "> **Predeclared Acceptance Gate**: ZERO FALSE_NEGATIVE, $\\le 2$ AMBIGUOUS, all TRUE_NEGATIVE at least MODERATE_CONFUSER.",
        "> Human review fields are left blank pending review by Satish.",
        "",
        "## Audit Overview",
        "",
        f"- **Total Candidates**: {len(audit_json_items)} items",
        f"- **Ecosystem Distribution**: PostgreSQL: {v2_audit_payload['ecosystem_distribution']['postgresql']}, "
        f"PyTorch: {v2_audit_payload['ecosystem_distribution']['pytorch']}, "
        f"Kubernetes: {v2_audit_payload['ecosystem_distribution']['kubernetes']}, "
        f"FastAPI: {v2_audit_payload['ecosystem_distribution']['fastapi']}",
        f"- **Typology Distribution**: Direct Lookup: {v2_audit_payload['typology_distribution']['direct_lookup']}, "
        f"Comparative: {v2_audit_payload['typology_distribution']['comparative_discrimination']}, "
        f"Troubleshooting: {v2_audit_payload['typology_distribution']['troubleshooting_scenario']}",
        "",
        "---",
        "",
        "## Audit Items",
        "",
    ]

    for item in audit_json_items:
        t_scores = item["teacher_scores"]
        s_pos_str = f"{t_scores['positive_score']:.4f}" if t_scores.get("positive_score") is not None else "N/A"
        s_neg_str = f"{t_scores['negative_score']:.4f}" if t_scores.get("negative_score") is not None else "N/A"
        margin_str = f"{t_scores['margin']:.4f}" if t_scores.get("margin") is not None else "N/A"
        md_lines.extend([
            f"### Item {item['item_index']:02d}: [{item['query_id']}] ({item['ecosystem'].upper()})",
            "",
            f"- **Query**: `{item['query_text']}`",
            f"- **Typology**: `{item['typology']}`",
            f"- **Hybrid Rank**: `#{item['hybrid_rank']}` (RRF: `{item['rrf_score']:.6f}`, Lexical: `{item['lexical_rank']}`, Dense: `{item['dense_rank']}`)",
            f"- **Teacher Scores**: $s_{{\\text{{pos}}}} = {s_pos_str}$, $s_{{\\text{{neg}}}} = {s_neg_str}$, Margin $\\Delta = {margin_str}$",
            f"- **Lexical Jaccard**: `{item['lexical_jaccard_overlap']:.4f}`",
            f"- **Query Entities**: `{item['query_entities']}`",
            f"- **Candidate Entities**: `{item['candidate_entities']}`",
            f"- **Entity Overlap**: `{item['entity_overlap']}`",
            f"- **Answer Functions**: `{item['answer_functions']}`",
            "",
            f"**Positive Chunk** (`{item['positive_chunk_id']}` | `{item['positive_source_path']}`):",
            f"> {item['positive_excerpt']}",
            "",
            f"**Proposed Negative Chunk** (`{item['hard_negative_chunk_id']}` | `{item['hard_negative_source_path']}`):",
            f"> {item['hard_negative_excerpt']}",
            "",
            "**Human Review Form:**",
            "```yaml",
            "decision: [PENDING: TRUE_NEGATIVE | FALSE_NEGATIVE | AMBIGUOUS]",
            "difficulty: [PENDING: HARD_CONFUSER | MODERATE_CONFUSER | TRIVIAL]",
            "reviewer: [PENDING: Satish]",
            "review_timestamp_utc: null",
            "reviewer_notes: \"\"",
            "```",
            "",
            "---",
            "",
        ])

    with open(out_audit_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Generated {out_audit_md}")


if __name__ == "__main__":
    main()
