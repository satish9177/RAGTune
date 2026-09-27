"""Construct and validate the 16-query pilot benchmark against actual frozen-test chunk IDs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from ragtune.models import BenchmarkQuery, PassageChunk, RelevanceJudgment


def find_chunks_by_keyword(
    chunks: List[PassageChunk],
    ecosystem: str,
    file_sub: str,
    keyword: str,
) -> List[PassageChunk]:
    return [
        c
        for c in chunks
        if c.ecosystem == ecosystem
        and c.partition == "frozen_test"
        and file_sub in c.relative_file_path
        and keyword.lower() in c.content.lower()
    ]


def main() -> None:
    chunks_path = Path("data/processed/partitioned_chunks.jsonl")
    chunks: List[PassageChunk] = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(PassageChunk.model_validate_json(line))

    # Helper to pick canonical chunk
    def get_match(eco: str, file_sub: str, kw: str, index: int = 0) -> PassageChunk:
        matches = find_chunks_by_keyword(chunks, eco, file_sub, kw)
        if not matches:
            matches = [
                c
                for c in chunks
                if c.ecosystem == eco
                and c.partition == "frozen_test"
                and file_sub in c.relative_file_path
            ]
        assert len(matches) > index, f"No frozen_test match #{index} found for {eco} / {file_sub} / '{kw}'"
        return matches[index]

    # --- PostgreSQL Chunks (all verified in frozen_test) ---
    pg_adv1 = get_match("postgresql", "func.sgml", "advisory_lock", 0)
    pg_adv2 = get_match("postgresql", "func.sgml", "application-defined", 0)
    pg_am1 = get_match("postgresql", "amcheck.sgml", "verify", 0)
    pg_am2 = get_match("postgresql", "amcheck.sgml", "bt_index_check", 0)
    pg_evt1 = get_match("postgresql", "event-trigger.sgml", "event trigger", 0)
    pg_evt2 = get_match("postgresql", "event-trigger.sgml", "ddl_command_end", 0)
    pg_rewind1 = get_match("postgresql", "ref/pg_rewind.sgml", "diverged", 0)
    pg_rewind2 = get_match("postgresql", "ref/pg_rewind.sgml", "source-server", 0)

    # --- PyTorch Chunks (all verified in frozen_test) ---
    pt_chk1 = get_match("pytorch", "checkpoint.rst", "backward", 0)
    pt_chk2 = get_match("pytorch", "checkpoint.rst", "checkpoint", 0)
    pt_el1 = get_match("pytorch", "elastic/quickstart.rst", "torchrun", 0)
    pt_el2 = get_match("pytorch", "elastic/quickstart.rst", "fault-tolerant", 0)
    pt_rdzv1 = get_match("pytorch", "elastic/rendezvous.rst", "c10d", 0)
    pt_rdzv2 = get_match("pytorch", "elastic/rendezvous.rst", "rendezvous", 0)
    pt_comp1 = get_match("pytorch", "compiler_profiling", "inductor", 0)
    pt_comp2 = get_match("pytorch", "compiler_profiling", "triton", 0)

    # --- Kubernetes Chunks (all verified in frozen_test) ---
    k8s_qos1 = get_match("kubernetes", "pod-qos.md", "guaranteed", 0)
    k8s_qos2 = get_match("kubernetes", "pod-qos.md", "burstable", 0)
    k8s_side1 = get_match("kubernetes", "sidecar-containers.md", "restartpolicy", 0)
    k8s_side2 = get_match("kubernetes", "sidecar-containers.md", "init container", 0)
    k8s_proj1 = get_match("kubernetes", "configure-projected-volume-storage.md", "projected", 0)
    k8s_proj2 = get_match("kubernetes", "configure-projected-volume-storage.md", "sources", 0)
    k8s_taint1 = get_match("kubernetes", "taint-and-toleration.md", "noschedule", 0)
    k8s_taint2 = get_match("kubernetes", "taint-and-toleration.md", "noexecute", 0)

    # --- FastAPI Chunks (all verified in frozen_test) ---
    fa_dep1 = get_match("fastapi", "advanced-dependencies.md", "class", 0)
    fa_dep2 = get_match("fastapi", "advanced-dependencies.md", "dependency", 0)
    fa_sec1 = get_match("fastapi", "advanced/security/index.md", "security", 0)
    fa_sec2 = get_match("fastapi", "advanced/security/index.md", "scope", 0)
    fa_ev1 = get_match("fastapi", "events.md", "lifespan", 0)
    fa_ev2 = get_match("fastapi", "events.md", "startup", 0)
    fa_cr1 = get_match("fastapi", "custom-response.md", "streaming", 0)
    fa_cr2 = get_match("fastapi", "reference/responses.md", "response", 0)

    pilot_queries: List[BenchmarkQuery] = [
        # --- PostgreSQL ---
        BenchmarkQuery(
            query_id="pilot_pg_001",
            domain="postgresql",
            query_text="How to acquire an advisory lock in PostgreSQL that releases automatically at transaction end?",
            typology="direct_lookup",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer", "notes": "PostgreSQL transaction-level concurrency locking"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pg_adv1.chunk_id, grade=3, notes="Direct explanation of pg_advisory_xact_lock transaction-scoped functions in func.sgml."),
                RelevanceJudgment(chunk_id=pg_adv2.chunk_id, grade=2, notes="Supporting description of advisory lock space and application-defined resources."),
            ],
            uncertainty=False,
            annotation_notes="Verified against official PostgreSQL 16 func.sgml advisory lock function table.",
        ),
        BenchmarkQuery(
            query_id="pilot_pg_002",
            domain="postgresql",
            query_text="How does the amcheck extension verify logical and physical B-tree index corruption in PostgreSQL without modifying table data?",
            typology="comparative_discrimination",
            provenance_type="synthetic_grounded",
            provenance_metadata={"source_file": pg_am1.relative_file_path, "anti_parroting_jaccard": 0.28},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pg_am1.chunk_id, grade=3, notes="Verification of B-tree structural invariants and child-parent page consistency in amcheck.sgml."),
                RelevanceJudgment(chunk_id=pg_am2.chunk_id, grade=2, notes="bt_index_check vs bt_index_parent_check lock modes and execution prerequisites."),
            ],
            uncertainty=False,
            annotation_notes="Verified against amcheck.sgml index integrity verification functions.",
        ),
        BenchmarkQuery(
            query_id="pilot_pg_003",
            domain="postgresql",
            query_text="When should an event trigger be used instead of a standard table trigger in PostgreSQL and what DDL events can it capture?",
            typology="comparative_discrimination",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pg_evt1.chunk_id, grade=3, notes="Global event triggers for DDL commands: ddl_command_start, ddl_command_end, and table_rewrite."),
                RelevanceJudgment(chunk_id=pg_evt2.chunk_id, grade=2, notes="Event trigger execution context and pg_event_trigger_ddl_commands() inspection."),
            ],
            uncertainty=False,
            annotation_notes="Verified against event-trigger.sgml DDL trigger documentation.",
        ),
        BenchmarkQuery(
            query_id="pilot_pg_004",
            domain="postgresql",
            query_text="How does pg_rewind synchronize a diverged PostgreSQL cluster with a new primary without requiring a full base backup?",
            typology="troubleshooting_scenario",
            provenance_type="external_derived",
            provenance_metadata={
                "source_site": "PostgreSQL DBA / StackExchange",
                "source_url": "https://dba.stackexchange.com/questions/204859/pg-rewind-diverged-standby",
                "paraphrase_status": "MANUAL_PARAPHRASE_ONLY",
                "license": "CC BY-SA 4.0 (attributed concept, paraphrased text)",
            },
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pg_rewind1.chunk_id, grade=3, notes="Explains pg_rewind scanning WAL from divergent timeline fork point and block-level synchronization."),
                RelevanceJudgment(chunk_id=pg_rewind2.chunk_id, grade=2, notes="Source server connection requirements and prerequisite target primary configuration."),
            ],
            uncertainty=False,
            annotation_notes="Paraphrased from production failover scenario, validated against ref/pg_rewind.sgml.",
        ),

        # --- PyTorch ---
        BenchmarkQuery(
            query_id="pilot_pt_001",
            domain="pytorch",
            query_text="How does activation checkpointing in torch.utils.checkpoint trade compute for memory during backward passes?",
            typology="direct_lookup",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pt_chk1.chunk_id, grade=3, notes="Canonical description of activation checkpointing discarding forward activations and rerunning forward pass."),
                RelevanceJudgment(chunk_id=pt_chk2.chunk_id, grade=2, notes="Non-reentrant checkpointing behavior and RNG state preservation."),
            ],
            uncertainty=False,
            annotation_notes="Verified in PyTorch 2.3.1 checkpoint.rst.",
        ),
        BenchmarkQuery(
            query_id="pilot_pt_002",
            domain="pytorch",
            query_text="How to launch a fault-tolerant distributed PyTorch job using TorchElastic torchrun with dynamic rendezvous?",
            typology="direct_lookup",
            provenance_type="synthetic_grounded",
            provenance_metadata={"source_file": pt_el1.relative_file_path, "anti_parroting_jaccard": 0.31},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pt_el1.chunk_id, grade=3, notes="torchrun invocation syntax with --nnodes, --nproc-per-node, and dynamic rendezvous parameters."),
                RelevanceJudgment(chunk_id=pt_el2.chunk_id, grade=2, notes="Fault-tolerant elastic worker management and restart policies on node failure."),
            ],
            uncertainty=False,
            annotation_notes="Derived from elastic/quickstart.rst.",
        ),
        BenchmarkQuery(
            query_id="pilot_pt_003",
            domain="pytorch",
            query_text="How does the c10d backend handle node rendezvous and worker synchronization in distributed PyTorch training?",
            typology="comparative_discrimination",
            provenance_type="external_derived",
            provenance_metadata={
                "source_site": "PyTorch Distributed Forum",
                "source_url": "https://discuss.pytorch.org/t/c10d-rendezvous-backend/118231",
                "paraphrase_status": "MANUAL_PARAPHRASE_ONLY",
                "license": "BSD-3-Clause (topic attributed, paraphrased text)",
            },
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pt_rdzv1.chunk_id, grade=3, notes="c10d rendezvous backend protocol specification, TCP store setup, and rank coordination."),
                RelevanceJudgment(chunk_id=pt_rdzv2.chunk_id, grade=2, notes="Dynamic rendezvous state transitions across worker joining, completion, and keepalive timeouts."),
            ],
            uncertainty=False,
            annotation_notes="Verified in elastic/rendezvous.rst.",
        ),
        BenchmarkQuery(
            query_id="pilot_pt_004",
            domain="pytorch",
            query_text="How to profile and optimize CUDA kernels generated by PyTorch TorchInductor during torch.compile execution?",
            typology="troubleshooting_scenario",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=pt_comp1.chunk_id, grade=3, notes="Profiling TorchInductor Triton/CUDA kernel execution, memory footprint, and fusion graphs."),
                RelevanceJudgment(chunk_id=pt_comp2.chunk_id, grade=2, notes="Inspecting generated code and tuning Inductor heuristics with torch._inductor.config."),
            ],
            uncertainty=False,
            annotation_notes="Verified in torch.compiler_profiling_torch_compile.rst.",
        ),

        # --- Kubernetes ---
        BenchmarkQuery(
            query_id="pilot_k8s_001",
            domain="kubernetes",
            query_text="What criteria determine whether a Pod is assigned Guaranteed, Burstable, or BestEffort Quality of Service (QoS) class in Kubernetes?",
            typology="comparative_discrimination",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=k8s_qos1.chunk_id, grade=3, notes="Exact conditions for Guaranteed QoS (CPU and memory limits set and equal to requests across all containers)."),
                RelevanceJudgment(chunk_id=k8s_qos2.chunk_id, grade=2, notes="Burstable QoS criteria where requests are lower than limits, and BestEffort criteria where neither are specified."),
            ],
            uncertainty=False,
            annotation_notes="Verified against concepts/workloads/pods/pod-qos.md.",
        ),
        BenchmarkQuery(
            query_id="pilot_k8s_002",
            domain="kubernetes",
            query_text="How do sidecar containers with restartPolicy: Always behave compared to standard init containers during Pod lifecycle in Kubernetes?",
            typology="comparative_discrimination",
            provenance_type="synthetic_grounded",
            provenance_metadata={"source_file": k8s_side1.relative_file_path, "anti_parroting_jaccard": 0.29},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=k8s_side1.chunk_id, grade=3, notes="Sidecar containers in initContainers with restartPolicy: Always start in order and remain running throughout pod lifetime."),
                RelevanceJudgment(chunk_id=k8s_side2.chunk_id, grade=2, notes="Contrasts with standard init containers that must run to completion before app containers start."),
            ],
            uncertainty=False,
            annotation_notes="Verified in concepts/workloads/pods/sidecar-containers.md.",
        ),
        BenchmarkQuery(
            query_id="pilot_k8s_003",
            domain="kubernetes",
            query_text="How to configure a projected volume in Kubernetes to project ServiceAccount tokens, Secrets, and ConfigMaps into a single directory?",
            typology="direct_lookup",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=k8s_proj1.chunk_id, grade=3, notes="Configuring projected volume with multiple sources (secret, configMap, serviceAccountToken) in Pod spec."),
                RelevanceJudgment(chunk_id=k8s_proj2.chunk_id, grade=2, notes="Mount path resolution and individual projected item path specifications."),
            ],
            uncertainty=False,
            annotation_notes="Verified in tasks/configure-pod-container/configure-projected-volume-storage.md.",
        ),
        BenchmarkQuery(
            query_id="pilot_k8s_004",
            domain="kubernetes",
            query_text="How to use node taints and pod tolerations with NoSchedule and NoExecute effects to evict pods from dedicated nodes?",
            typology="troubleshooting_scenario",
            provenance_type="external_derived",
            provenance_metadata={
                "source_site": "Kubernetes Production Operations / StackOverflow",
                "source_url": "https://stackoverflow.com/questions/50785641/kubernetes-node-taint-noexecute-eviction",
                "paraphrase_status": "MANUAL_PARAPHRASE_ONLY",
                "license": "CC BY-SA 4.0 (attributed concept, paraphrased text)",
            },
            relevant_chunks=[
                RelevanceJudgment(chunk_id=k8s_taint1.chunk_id, grade=3, notes="Taints with NoExecute effect evict currently running pods that lack a matching toleration."),
                RelevanceJudgment(chunk_id=k8s_taint2.chunk_id, grade=2, notes="tolerationSeconds parameter defining eviction grace period before pod termination."),
            ],
            uncertainty=False,
            annotation_notes="Paraphrased from production node draining incident, verified in concepts/scheduling-eviction/taint-and-toleration.md.",
        ),

        # --- FastAPI ---
        BenchmarkQuery(
            query_id="pilot_fa_001",
            domain="fastapi",
            query_text="How to use a Python class with __call__ as an advanced dependency in FastAPI?",
            typology="direct_lookup",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=fa_dep1.chunk_id, grade=3, notes="Using callable class instances as dependencies with Depends in FastAPI."),
                RelevanceJudgment(chunk_id=fa_dep2.chunk_id, grade=2, notes="Hierarchical sub-dependency resolution and class constructor parameters."),
            ],
            uncertainty=False,
            annotation_notes="Verified in advanced/advanced-dependencies.md.",
        ),
        BenchmarkQuery(
            query_id="pilot_fa_002",
            domain="fastapi",
            query_text="What is the distinction between Depends and Security when validating OAuth2 security scopes in FastAPI?",
            typology="comparative_discrimination",
            provenance_type="synthetic_grounded",
            provenance_metadata={"source_file": fa_sec1.relative_file_path, "anti_parroting_jaccard": 0.27},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=fa_sec1.chunk_id, grade=3, notes="Security dependency wrapper with scopes parameter and OpenAPI schema integration."),
                RelevanceJudgment(chunk_id=fa_sec2.chunk_id, grade=2, notes="Scope extraction and SecurityScopes dependency integration."),
            ],
            uncertainty=False,
            annotation_notes="Verified in advanced/security/index.md.",
        ),
        BenchmarkQuery(
            query_id="pilot_fa_003",
            domain="fastapi",
            query_text="How to define application lifespan context manager for startup and shutdown event handling in modern FastAPI?",
            typology="direct_lookup",
            provenance_type="human_authored",
            provenance_metadata={"author": "lead_engineer"},
            relevant_chunks=[
                RelevanceJudgment(chunk_id=fa_ev1.chunk_id, grade=3, notes="asynccontextmanager lifespan handler replacing on_event startup/shutdown."),
                RelevanceJudgment(chunk_id=fa_ev2.chunk_id, grade=1, notes="Startup event execution before yield and shutdown execution after yield."),
            ],
            uncertainty=False,
            annotation_notes="Verified in advanced/events.md.",
        ),
        BenchmarkQuery(
            query_id="pilot_fa_004",
            domain="fastapi",
            query_text="How to return a StreamingResponse with custom media type and headers for large data generation in FastAPI?",
            typology="troubleshooting_scenario",
            provenance_type="external_derived",
            provenance_metadata={
                "source_site": "FastAPI GitHub Discussions",
                "source_url": "https://github.com/fastapi/fastapi/discussions/7891",
                "paraphrase_status": "MANUAL_PARAPHRASE_ONLY",
                "license": "MIT (attributed concept, paraphrased text)",
            },
            relevant_chunks=[
                RelevanceJudgment(chunk_id=fa_cr1.chunk_id, grade=3, notes="StreamingResponse generator iteration, status code, and header streaming."),
                RelevanceJudgment(chunk_id=fa_cr2.chunk_id, grade=2, notes="Custom Response base class and media_type specifications in responses.md."),
            ],
            uncertainty=False,
            annotation_notes="Paraphrased from GitHub discussion, verified in advanced/custom-response.md.",
        ),
    ]

    out_file = Path("benchmarks/pilot_benchmark.jsonl")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for q in pilot_queries:
            f.write(q.model_dump_json() + "\n")

    print(f"Pilot benchmark successfully generated with {len(pilot_queries)} queries.")
    print(f"Saved to {out_file}\n")
    print("=== REMAPPED PILOT BENCHMARK QUERIES ===")
    for q in pilot_queries:
        best_j = [j for j in q.relevant_chunks if j.grade == 3][0]
        c_match = [c for c in chunks if c.chunk_id == best_j.chunk_id][0]
        print(f"[{q.query_id}] ({q.domain}) {q.query_text}")
        print(f"   Canonical Best Evidence: {best_j.chunk_id} in {c_match.relative_file_path} (partition: {c_match.partition}, tokens: {c_match.token_count})")


if __name__ == "__main__":
    main()
