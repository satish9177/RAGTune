"""Unit and integrity tests for Benchmark v0 and E0-v0 baseline artifacts."""

import json
from pathlib import Path
import pytest

from ragtune.training.guardrails import validate_validation_query


def test_benchmark_v0_schema_and_integrity():
    benchmark_path = Path("benchmarks/benchmark_v0.jsonl")
    assert benchmark_path.exists(), "Benchmark v0 file must exist"

    with open(benchmark_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    assert len(queries) == 140, f"Expected 140 queries, got {len(queries)}"

    domains = {}
    typologies = {}
    provenances = {}

    for q in queries:
        validate_validation_query(q)
        assert q["source_partition"] == "validation"
        assert q["role"] == "development"
        assert q["review_status"] in ["AWAITING_HUMAN_REVIEW", "AI_SOURCE_VERIFIED"]
        assert q["reviewer"] is None
        assert q["provenance_type"] != "human_authored", "AI generated queries must not be labeled human_authored"
        assert q["provenance_type"] in ["ai_authored_project_query", "synthetic_grounded", "external_derived_verified"]
        assert q["ai_recommendation"] in ["APPROVE_CANDIDATE", "REVISE_CANDIDATE", "REJECT_CANDIDATE"]

        d = q["domain"]
        t = q["typology"]
        p = q["provenance_type"]

        domains[d] = domains.get(d, 0) + 1
        typologies[t] = typologies.get(t, 0) + 1
        provenances[p] = provenances.get(p, 0) + 1

        # Check relevant chunks: must have exactly one grade 3 canonical chunk, and total positives >= 1
        grades = [r["grade"] for r in q["relevant_chunks"]]
        assert grades.count(3) == 1, f"Query {q['query_id']} must have exactly one grade 3 canonical chunk"
        assert len(grades) >= 1

    assert domains == {"postgresql": 35, "pytorch": 35, "kubernetes": 35, "fastapi": 35}
    assert typologies == {"direct_lookup": 40, "comparative_discrimination": 60, "troubleshooting_scenario": 40}
    assert provenances["ai_authored_project_query"] == 88
    assert provenances["synthetic_grounded"] == 49
    assert provenances["external_derived_verified"] == 3

    awaiting_human = sum(1 for q in queries if q["review_status"] == "AWAITING_HUMAN_REVIEW")
    ai_verified = sum(1 for q in queries if q["review_status"] == "AI_SOURCE_VERIFIED")
    assert awaiting_human == 40
    assert ai_verified == 100

    # Verify exact Stack Overflow licenses based on contribution dates
    so_queries = {q["query_id"]: q for q in queries if q["provenance_type"] == "external_derived_verified"}
    assert len(so_queries) == 3
    assert so_queries["v0_pg_026"]["provenance_metadata"]["license"] == "CC BY-SA 2.5"
    assert so_queries["v0_pt_018"]["provenance_metadata"]["license"] == "CC BY-SA 3.0"
    assert so_queries["v0_fa_028"]["provenance_metadata"]["license"] == "CC BY-SA 4.0"


def test_e0_v0_manifest_and_metrics_artifacts():
    manifest_path = Path("benchmarks/e0_v0_manifest.json")
    metrics_path = Path("benchmarks/e0_v0_metrics.json")
    preds_path = Path("benchmarks/e0_v0_predictions.jsonl")
    failures_path = Path("benchmarks/e0_v0_failures.jsonl")

    assert manifest_path.exists()
    assert metrics_path.exists()
    assert preds_path.exists()
    assert failures_path.exists()

    with open(manifest_path, "r", encoding="utf-8") as f:
        man = json.load(f)

    assert man["total_queries"] == 140
    assert man["benchmark_source_partition"] == "validation"
    assert man["status"] == "PROVISIONAL_DRAFT"
    assert man["canonical_status"] == "PENDING_BENCHMARK_V0_HUMAN_REVIEW"
    assert "overall_metrics" in man
    assert man["overall_metrics"]["recall_at_10"] > 0.40


def test_quality_audit_and_review_packets_exist():
    audit_file = Path("benchmarks/benchmark_v0_quality_audit.json")
    master_review = Path("benchmarks/review/benchmark_v0_review.md")
    csv_review = Path("benchmarks/review/benchmark_v0_review.csv")
    json_review = Path("benchmarks/review/benchmark_v0_review.json")
    human_audit_40 = Path("benchmarks/review/HUMAN_AUDIT_40.md")
    sample_ids_file = Path("benchmarks/review/human_audit_sample_ids.json")

    assert audit_file.exists()
    assert master_review.exists()
    assert csv_review.exists()
    assert json_review.exists()
    assert human_audit_40.exists()
    assert sample_ids_file.exists()

    with open(audit_file, "r", encoding="utf-8") as f:
        audit = json.load(f)

    assert audit["total_queries_audited"] == 140
    assert audit["review_status_summary"]["AWAITING_HUMAN_REVIEW"] == 40
    assert audit["review_status_summary"]["AI_SOURCE_VERIFIED"] == 100
    assert audit["anti_parroting_summary"]["max_jaccard_vs_evidence"] < 0.40

    with open(sample_ids_file, "r", encoding="utf-8") as f:
        sample_manifest = json.load(f)
    assert sample_manifest["human_audit_sample_count"] == 40
    assert len(sample_manifest["sample_query_ids"]) == 40


def test_post_repair_evidence_relevance():
    """Verify that 100% of benchmark v0 queries have strong, answer-bearing evidence."""
    from scripts.evidence_verifier import is_generic_intro, extract_answer_span

    report_path = Path("benchmarks/post_repair_evidence_audit_report.json")
    assert report_path.exists(), "Post-repair evidence audit report must exist"

    with open(report_path, "r", encoding="utf-8") as f:
        rep = json.load(f)

    assert rep["summary"]["total_queries"] == 140
    assert rep["summary"]["evidence_strong"] == 140
    assert rep["summary"]["evidence_needs_review"] == 0
    assert rep["summary"]["evidence_invalid"] == 0
    assert rep["summary"]["evidence_strong_percentage"] == 100.0

    # Load validation partition chunks
    chunks_by_id = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            if item.get("partition") == "validation":
                chunks_by_id[item["chunk_id"]] = item

    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    for q in queries:
        qid = q["query_id"]
        g3_refs = [r for r in q["relevant_chunks"] if r["grade"] == 3]
        assert len(g3_refs) == 1, f"{qid} must have exactly one Grade 3 chunk"
        g3_cid = g3_refs[0]["chunk_id"]
        assert g3_cid in chunks_by_id, f"{qid} Grade 3 chunk {g3_cid} must be in validation partition"
        g3_chunk = chunks_by_id[g3_cid]

        # Zero Grade 3 chunks may match generic intro patterns
        assert not is_generic_intro(g3_chunk["content"]), (
            f"{qid} Grade 3 chunk {g3_cid} matched generic intro pattern!"
        )

        # Ensure answer span extractor can find focused span
        query_words = [w.strip("?,.:;\"'`()[]{}") for w in q["query_text"].split() if len(w) > 3]
        span = extract_answer_span(g3_chunk["content"], query_words, window_chars=250)
        assert len(span) > 20, f"{qid} failed to produce a valid answer span"

    # Specific check for rejected & replaced v0_pt_027
    pt_027 = next(q for q in queries if q["query_id"] == "v0_pt_027")
    assert "memory" in pt_027["query_text"].lower()
    assert "dev/shm" not in pt_027["query_text"].lower()
    assert "bus error" not in pt_027["query_text"].lower()
    g3_pt027 = pt_027["relevant_chunks"][0]["chunk_id"]
    pt027_content = chunks_by_id[g3_pt027]["content"]
    assert "exception" in pt027_content.lower()
    assert "stack frame" in pt027_content.lower()


def test_human_audit_packet_v2_structure():
    """Verify that HUMAN_AUDIT_40_V2.md exists and adheres to review contract."""
    packet_v2 = Path("benchmarks/review/HUMAN_AUDIT_40_V2.md")
    assert packet_v2.exists(), "HUMAN_AUDIT_40_V2.md must exist"

    text = packet_v2.read_text(encoding="utf-8")

    # Historical packet must also be preserved
    assert Path("benchmarks/review/HUMAN_AUDIT_40.md").exists()

    # Must contain 40 query sections
    assert "Total Audit Sample** | **40**" in text
    for i in range(1, 41):
        assert f"### {i}. `[" in text, f"Missing section for item {i}"

    # Must contain explicit badges for previous human decisions (in summary list, table, and item headers)
    assert text.count("[PREVIOUSLY APPROVED - EVIDENCE PRESERVED]") == 11  # 1 summary + 5 table + 5 items
    assert text.count("[PREVIOUSLY REJECTED - QUERY & EVIDENCE REPLACED]") == 3  # 1 summary + 1 table + 1 item
    assert text.count("[PREVIOUSLY REVISE - QUERY & EVIDENCE REPLACED]") == 13  # 1 summary + 6 table + 6 items
    assert text.count("[PREVIOUSLY REVISE - EVIDENCE RE-ANCHORED]") == 57  # 1 summary + 28 table + 28 items

    # Review checkboxes must be unselected (zero simulated decisions)
    assert text.count("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**") == 40
    assert "AWAITING_HUMAN_REVIEW" in text


def test_v3_human_audit_packet_and_spec_consistency():
    """Verify Benchmark v0 canonical specs, JSONL dataset, and HUMAN_AUDIT_40_V3.md consistency."""
    from scripts.benchmark_specs import BENCHMARK_V0_SPECS

    # 1. Verify specs vs JSONL dataset
    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    assert len(queries) == 140
    assert len(BENCHMARK_V0_SPECS) == 140

    q_by_id = {q["query_id"]: q for q in queries}

    for spec in BENCHMARK_V0_SPECS:
        qid, eco, qtext, prov, meta, unc, rec, g3, g2s, g1s = spec
        assert qid in q_by_id, f"Missing {qid} in benchmark_v0.jsonl"
        q = q_by_id[qid]
        assert q["query_text"] == qtext, f"Query text mismatch for {qid}: '{q['query_text']}' != '{qtext}'"
        assert q["domain"] == eco
        assert q["provenance_type"] == prov

        # Canonical Grade 3 match
        g3_refs = [r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3]
        assert len(g3_refs) == 1
        assert g3_refs[0].startswith(g3), f"{qid} G3 prefix mismatch: {g3_refs[0]} vs {g3}"

        # Grade 2 match
        g2_refs = [r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 2]
        assert len(g2_refs) == len(g2s)
        for pfx, cid in zip(g2s, g2_refs):
            assert cid.startswith(pfx)

        # Grade 1 match
        g1_refs = [r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 1]
        assert len(g1_refs) == len(g1s)
        for pfx, cid in zip(g1s, g1_refs):
            assert cid.startswith(pfx)

    # 2. Verify HUMAN_AUDIT_40_V3.md
    packet_v3 = Path("benchmarks/review/HUMAN_AUDIT_40_V3.md")
    assert packet_v3.exists(), "HUMAN_AUDIT_40_V3.md must exist"
    packet_text = packet_v3.read_text(encoding="utf-8")

    with open("benchmarks/review/human_audit_sample_ids.json", "r", encoding="utf-8") as f:
        sample_manifest = json.load(f)
    sample_qids = sample_manifest["sample_query_ids"]
    assert len(sample_qids) == 40

    # Ensure all 40 sample queries exist in V3 packet
    for qid in sample_qids:
        assert f"[{qid}]" in packet_text, f"Missing query section for {qid} in HUMAN_AUDIT_40_V3.md"
        q = q_by_id[qid]
        g3_cid = next(r["chunk_id"] for r in q["relevant_chunks"] if r["grade"] == 3)

        # Verify reported_new_grade3_chunk == actual_grade3_chunk
        assert f"| `{g3_cid[:12]}` |" in packet_text, f"Summary table missing canonical chunk {g3_cid[:12]} for {qid}"
        assert f"Chunk ID: `{g3_cid[:12]}`" in packet_text, f"Item section missing canonical chunk {g3_cid[:12]} for {qid}"

    # Verify zero simulated human approvals
    for qid in sample_qids:
        q = q_by_id[qid]
        assert q["review_status"] == "AWAITING_HUMAN_REVIEW"
        assert q["reviewer"] is None
        assert q["reviewed_at"] is None

    assert packet_text.count("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**") == 40
    assert "- [x]" not in packet_text and "- [X]" not in packet_text

    # Verify badge counts: 18 Approved As-Is + 22 Repaired
    assert packet_text.count("[HUMAN-AUDIT APPROVED AS-IS]") == 37  # 1 intro + 18 table + 18 items
    assert packet_text.count("[POST-REVISE REPAIRED]") == 45  # 1 intro + 22 table + 22 items


def test_v3_grade2_and_comparative_relevance():
    """Verify semantic connection for Grade 2 chunks and coverage of both sides for comparative queries."""
    import re

    chunks_by_id = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            if item.get("partition") == "validation":
                chunks_by_id[item["chunk_id"]] = item

    with open("benchmarks/benchmark_v0.jsonl", "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]
    q_by_id = {q["query_id"]: q for q in queries}

    # 1. No Grade-2 evidence is marked when it has no semantic connection to the query
    stopwords = {
        "what", "when", "where", "which", "does", "that", "this", "with", "from",
        "into", "than", "more", "most", "other", "some", "such", "only", "same",
        "have", "been", "being", "between", "during", "regarding", "versus", "across", "using"
    }

    for q in queries:
        qid = q["query_id"]
        tokens = re.findall(r"[A-Za-z0-9_]+", q["query_text"].lower())
        kw = [w for w in tokens if len(w) > 3 and w not in stopwords]

        for r in q["relevant_chunks"]:
            if r["grade"] == 2:
                cid = r["chunk_id"]
                c = chunks_by_id[cid]
                text = (c["content"] + " " + c.get("breadcrumb", "")).lower()
                overlap = [k for k in kw if k in text]
                assert len(overlap) > 0, (
                    f"Grade 2 chunk {cid[:12]} for {qid} has zero keyword connection to query: kw={kw}"
                )

    # 2. Comparative queries cover every named side across Grade >= 2 evidence
    comparative_checks = [
        ("v0_k8s_015", ["recreate", "rollingupdate"]),
        ("v0_fa_023", ["root_path", "root-path"]),
        ("v0_k8s_007", ["readwriteonce", "readwriteoncepod"]),
        ("v0_pg_011", ["synchronous_commit", "remote_write"]),
        ("v0_k8s_022", ["rolebinding", "clusterrolebinding"]),
        ("v0_fa_018", ["allow_origins", "credential"]),
        ("v0_pt_002", ["create_graph", "grad"]),
        ("v0_pt_021", ["file_descriptor", "file_system"]),
        ("v0_pt_023", ["symmetric", "asymmetric"]),
    ]

    for qid, terms in comparative_checks:
        q = q_by_id[qid]
        g2_and_3 = [chunks_by_id[r["chunk_id"]]["content"].lower() for r in q["relevant_chunks"] if r["grade"] >= 2]
        combined = " ".join(g2_and_3)
        for term in terms:
            assert term in combined, f"Comparative query {qid} does not cover named term '{term}' across Grade >= 2 passages"


def test_v3_evidence_sanity_audit_report():
    """Verify benchmarks/v3_evidence_audit_report.json status."""
    report_path = Path("benchmarks/v3_evidence_audit_report.json")
    assert report_path.exists(), "v3_evidence_audit_report.json must exist"

    with open(report_path, "r", encoding="utf-8") as f:
        rep = json.load(f)

    assert rep["summary"]["total_queries"] == 140
    assert rep["summary"]["automated_check_fail"] == 0
    assert rep["summary"]["automated_check_pass"] == 139
    assert rep["summary"]["automated_check_review"] == 1
    assert rep["details"]["AUTOMATED_CHECK_REVIEW"][0]["query_id"] == "v0_fa_018"


def test_v3_human_audit_9_final():
    """Verify benchmarks/review/HUMAN_AUDIT_9_FINAL.md packet."""
    packet_path = Path("benchmarks/review/HUMAN_AUDIT_9_FINAL.md")
    assert packet_path.exists(), "HUMAN_AUDIT_9_FINAL.md must exist"

    text = packet_path.read_text(encoding="utf-8")
    target_qids = [
        "v0_pg_002", "v0_pg_011", "v0_pg_013", "v0_pg_016", "v0_pg_017",
        "v0_pg_018", "v0_pt_021", "v0_pt_032", "v0_k8s_007"
    ]

    for qid in target_qids:
        assert f"[{qid}]" in text, f"Missing {qid} in HUMAN_AUDIT_9_FINAL.md"

    # Exactly 9 unselected decision blocks
    assert text.count("- [ ] **APPROVE**  |  - [ ] **REVISE**  |  - [ ] **REJECT**") == 9
    assert "- [x]" not in text and "- [X]" not in text
    assert "PENDING_HUMAN_REVIEW" in text



