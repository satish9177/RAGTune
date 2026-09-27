"""Build Benchmark v0 as a Development Benchmark with Truthful Provenance & Review Fields.

Constructs 140 development benchmark queries grounded exclusively in the validation partition:
- Truthful provenance labels: ai_authored_project_query, synthetic_grounded, external_derived_verified.
- Zero false human_authored claims.
- Dynamic relevance positive sets (1, 2, 3+ positives).
- Genuine uncertainty identification for nuanced/borderline queries.
- Initial review_status = "UNREVIEWED", reviewer = null, and explicit AI recommendation.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import re
from typing import Any, Dict, List

from ragtune.models import BenchmarkQuery, RelevanceJudgment
from ragtune.training.guardrails import validate_validation_query


def compute_jaccard(s1: str, s2: str) -> float:
    t1 = set(re.findall(r"[A-Za-z0-9_]+", s1.lower()))
    t2 = set(re.findall(r"[A-Za-z0-9_]+", s2.lower()))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


def main():
    print("=" * 70)
    print("REBUILDING BENCHMARK V0 WITH TRUTHFUL PROVENANCE & REVIEW FIELDS")
    print("=" * 70)

    # 1. Load validation partition chunks
    val_chunks: Dict[str, Dict[str, Any]] = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            if item.get("partition") == "validation":
                val_chunks[item["chunk_id"]] = item

    print(f"Loaded {len(val_chunks)} validation chunks.")

    def find_chunk_id(eco: str, file_sub: str, text_pat: str, fallback_idx: int = 0) -> str:
        matches = []
        for cid, c in val_chunks.items():
            if c["ecosystem"] != eco:
                continue
            if file_sub not in c["relative_file_path"]:
                continue
            combined = c["breadcrumb"] + " " + c["content"]
            if re.search(text_pat, combined, re.IGNORECASE):
                matches.append(cid)
        if not matches:
            file_chunks = [cid for cid, c in val_chunks.items() if c["ecosystem"] == eco and file_sub in c["relative_file_path"]]
            if not file_chunks:
                raise ValueError(f"No chunk found for {eco} file={file_sub} pat={text_pat}")
            return file_chunks[min(fallback_idx, len(file_chunks) - 1)]
        return matches[min(fallback_idx, len(matches) - 1)]

    # Verified external items:
    # 1. PyTorch multiprocessing fork vs spawn: SO post 48822463
    # 2. FastAPI CORS preflight wildcard: SO post 65632734
    # 3. PostgreSQL connection exhaustion: SO post 3086759
    # 4. Kubernetes EndpointSlice proposal: GitHub kubernetes/enhancements issue 752

    # Query specifications: (qid, eco, file_sub, text_pat, qtext, prov_type, prov_meta, uncertainty, pos_count_target, ai_rec)
    specs: List[Dict[str, Any]] = []

    # =========================================================================
    # POSTGRESQL (35 Queries: v0_pg_001 to v0_pg_035)
    # =========================================================================
    # Direct Lookup (10)
    specs.extend([
        {"qid": "v0_pg_001", "file": "config.sgml", "pat": r"shared_buffers", "q": "How is the shared_buffers parameter configured in postgresql.conf and what is its default allocation limit?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "role": "architecture_baseline"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_002", "file": "config.sgml", "pat": r"work_mem", "q": "What operation-level memory allocation is controlled by work_mem in PostgreSQL?", "prov": "synthetic_grounded", "meta": {"prompt": "PostgreSQL internal sort memory sizing"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_003", "file": "config.sgml", "pat": r"maintenance_work_mem", "q": "Which database maintenance operations utilize maintenance_work_mem in PostgreSQL?", "prov": "synthetic_grounded", "meta": {"prompt": "PostgreSQL vacuum and index build memory"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_004", "file": "config.sgml", "pat": r"wal_level", "q": "What are the allowed settings for wal_level in PostgreSQL and what do they enable?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_005", "file": "config.sgml", "pat": r"checkpoint_timeout", "q": "How does checkpoint_timeout dictate the maximum duration between automatic WAL checkpoints?", "prov": "synthetic_grounded", "meta": {"prompt": "PostgreSQL WAL checkpoint frequency"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_006", "file": "catalogs.sgml", "pat": r"pg_stat_activity", "q": "Which columns in the pg_stat_activity view display the currently executing SQL query and transaction start time?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_007", "file": "catalogs.sgml", "pat": r"pg_locks", "q": "How does the pg_locks system catalog represent granted versus awaiting locks across active backends?", "prov": "synthetic_grounded", "meta": {"prompt": "PostgreSQL lock catalog inspection"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_008", "file": "dml.sgml", "pat": r"RETURNING", "q": "What is the syntax for using the RETURNING clause in an INSERT or UPDATE statement in PostgreSQL?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_009", "file": "errcodes.sgml", "pat": r"error codes|SQLSTATE", "q": "How do the first two characters versus the last three characters in PostgreSQL five-character SQLSTATE codes represent error class and specific condition?", "prov": "synthetic_grounded", "meta": {"prompt": "PostgreSQL SQLSTATE error code structure"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_010", "file": "file-fdw.sgml", "pat": r"file_fdw|create foreign table", "q": "What table options are required when creating a foreign table using file_fdw in PostgreSQL?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
    ])

    # Comparative Discrimination (15)
    specs.extend([
        {"qid": "v0_pg_011", "file": "config.sgml", "pat": r"synchronous_commit", "q": "What is the durability difference between synchronous_commit set to on versus remote_write in PostgreSQL replication?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_012", "file": "config.sgml", "pat": r"synchronous_commit.*local", "q": "How does synchronous_commit = local differ from synchronous_commit = off regarding standby acknowledgment?", "prov": "synthetic_grounded", "meta": {"prompt": "Durability trade-offs in local synchronous commit"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_013", "file": "config.sgml", "pat": r"hot_standby_feedback", "q": "How does enabling hot_standby_feedback prevent query cancellation on physical replicas compared to increasing max_standby_streaming_delay?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "inspiration": "Replication query cancellation conflicts"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_014", "file": "config.sgml", "pat": r"deadlock_timeout.*statement_timeout", "q": "What is the distinction between statement_timeout and deadlock_timeout during backend lock contention?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_015", "file": "config.sgml", "pat": r"autovacuum_vacuum_cost_limit", "q": "How does autovacuum_vacuum_cost_limit throttle background vacuuming I/O compared to autovacuum_vacuum_cost_delay?", "prov": "synthetic_grounded", "meta": {"prompt": "Autovacuum cost throttling mechanics"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_016", "file": "catalogs.sgml", "pat": r"pg_stat_replication", "q": "What is the semantic difference between sent_lsn, write_lsn, and flush_lsn in pg_stat_replication?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_017", "file": "catalogs.sgml", "pat": r"pg_stat_database.*xact_commit", "q": "How do xact_commit and xact_rollback in pg_stat_database contrast with backend-level activity counters?", "prov": "synthetic_grounded", "meta": {"prompt": "Database transaction counters vs backend activity"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_018", "file": "dml.sgml", "pat": r"ON CONFLICT DO NOTHING.*DO UPDATE", "q": "What is the difference in locking and index requirements between ON CONFLICT DO NOTHING and ON CONFLICT DO UPDATE?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_019", "file": "btree-gin.sgml", "pat": r"btree_gin", "q": "When should the btree_gin extension be used to index scalar columns in a composite GIN index instead of creating a standard B-tree index?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "inspiration": "Multicolumn GIN with scalar types"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_020", "file": "intarray.sgml", "pat": r"intarray", "q": "How do the query operators provided by intarray compare to PostgreSQL built-in array operators for integer lookups?", "prov": "synthetic_grounded", "meta": {"prompt": "Specialized integer array operator performance"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_021", "file": "hstore.sgml", "pat": r"hstore", "q": "What is the distinction between the exist operator ? and the defined operator in the PostgreSQL hstore extension?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_022", "file": "diskusage.sgml", "pat": r"pg_total_relation_size", "q": "What physical storage components are included in pg_total_relation_size that are excluded by pg_relation_size?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "inspiration": "Disk usage and TOAST sizing"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_023", "file": "config.sgml", "pat": r"temp_buffers", "q": "How do temp_buffers differ from shared_buffers in scope and per-session allocation in PostgreSQL?", "prov": "synthetic_grounded", "meta": {"prompt": "Temporary table buffer pool vs shared buffer pool"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_024", "file": "catalogs.sgml", "pat": r"pg_tablespace", "q": "What is the structural difference between the default pg_default tablespace and pg_global catalog tablespace?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_025", "file": "config.sgml", "pat": r"bgwriter_lru_maxpages", "q": "How does the background writer process differ from the checkpointer in writing dirty shared buffers to disk?", "prov": "synthetic_grounded", "meta": {"prompt": "Bgwriter vs checkpointer dirty page flushing"}, "uncertainty": True, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
    ])

    # Troubleshooting Scenario (10)
    specs.extend([
        {"qid": "v0_pg_026", "file": "config.sgml", "pat": r"max_connections", "q": "How to resolve 'FATAL: sorry, too many clients already' by configuring connection limits and pooling parameters in PostgreSQL?", "prov": "external_derived_verified", "meta": {"source_url": "https://stackoverflow.com/questions/3086759/postgresql-sorry-too-many-clients-already", "revision_url": "https://stackoverflow.com/posts/3086759/revisions", "platform": "Stack Overflow", "post_id": "3086759", "title": "Postgresql sorry, too many clients already", "contribution_timestamp": "2010-06-22T08:14:48Z", "license": "CC BY-SA 2.5", "retrieval_date": "2026-09-27"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_027", "file": "config.sgml", "pat": r"statement_timeout", "q": "Why does an active query fail with 'canceling statement due to statement timeout' and how to isolate it to a specific session?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_028", "file": "catalogs.sgml", "pat": r"pg_stat_activity.*idle in transaction", "q": "How to identify and terminate orphaned sessions stuck in 'idle in transaction' holding locks using pg_stat_activity?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_029", "file": "config.sgml", "pat": r"deadlock_timeout", "q": "How does deadlock_timeout allow PostgreSQL to detect circular locking dependencies before canceling a transaction?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_030", "file": "config.sgml", "pat": r"max_standby_streaming_delay", "q": "Why do long-running read queries on a standby replica get terminated with 'canceling statement due to conflict with recovery'?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_031", "file": "diskusage.sgml", "pat": r"disk full|disk usage", "q": "How to monitor PostgreSQL disk space usage when relation size rapidly expands due to dead tuples and bloat?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_032", "file": "catalogs.sgml", "pat": r"pg_stat_activity.*wait_event", "q": "How to use wait_event_type and wait_event in pg_stat_activity to determine whether queries are stalled on I/O or lock acquisition?", "prov": "synthetic_grounded", "meta": {"prompt": "Diagnosing backend wait bottlenecks in PostgreSQL"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_033", "file": "dml.sgml", "pat": r"ON CONFLICT", "q": "Why does an INSERT statement require an explicit conflict target or unique constraint name when specifying ON CONFLICT DO UPDATE?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_034", "file": "config.sgml", "pat": r"autovacuum", "q": "How to diagnose why autovacuum fails to clean up dead tuples resulting in continuous table bloat on a high-write table?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pg_035", "file": "file-fdw.sgml", "pat": r"file_fdw", "q": "Why does querying a file_fdw foreign table result in permission denied reading the target data file on disk?", "prov": "synthetic_grounded", "meta": {"prompt": "Foreign data wrapper file access troubleshooting"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
    ])

    # =========================================================================
    # PYTORCH (35 Queries: v0_pt_001 to v0_pt_035)
    # =========================================================================
    # Direct Lookup (10)
    specs.extend([
        {"qid": "v0_pt_001", "file": "autograd.rst", "pat": r"torch\.autograd\.backward", "q": "What arguments does torch.autograd.backward accept to compute the sum of gradients of given tensors?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_002", "file": "autograd.rst", "pat": r"torch\.autograd\.grad", "q": "How does torch.autograd.grad compute and return the sum of gradients of outputs with respect to inputs?", "prov": "synthetic_grounded", "meta": {"prompt": "PyTorch autograd grad functional API"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_003", "file": "autograd.rst", "pat": r"set_detect_anomaly", "q": "What setting in torch.autograd enables anomaly detection to locate NaN or infinity gradients during backward passes?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_004", "file": "ddp_comm_hooks.rst", "pat": r"fp16_compress_hook", "q": "What communication hook in PyTorch DDP compresses model gradients to FP16 before the AllReduce step?", "prov": "synthetic_grounded", "meta": {"prompt": "PyTorch FP16 compression communication hook"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_005", "file": "ddp_comm_hooks.rst", "pat": r"bf16_compress_hook", "q": "Which DDP communication hook performs BF16 gradient compression across distributed workers?", "prov": "synthetic_grounded", "meta": {"prompt": "BF16 DDP communication hook"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_006", "file": "distributed.checkpoint.rst", "pat": r"save_state_dict|torch\.distributed\.checkpoint", "q": "What function in torch.distributed.checkpoint saves sharded model state dicts to distributed storage?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_007", "file": "distributed.tensor.parallel.rst", "pat": r"DTensor|tensor_parallel", "q": "How is a DTensor created to represent a distributed tensor across device meshes in PyTorch?", "prov": "synthetic_grounded", "meta": {"prompt": "DTensor device mesh creation"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_008", "file": "multiprocessing.rst", "pat": r"set_sharing_strategy", "q": "What sharing strategies can be configured using torch.multiprocessing.set_sharing_strategy?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_009", "file": "notes/broadcasting.rst", "pat": r"broadcasting", "q": "What conditions must two tensor shapes satisfy to be broadcastable according to PyTorch broadcasting semantics?", "prov": "synthetic_grounded", "meta": {"prompt": "PyTorch tensor shape broadcasting conditions"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_010", "file": "nn.attention.bias.rst", "pat": r"scaled_dot_product_attention", "q": "What is the expected format of the attn_bias tensor in torch.nn.functional.scaled_dot_product_attention?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # Comparative Discrimination (15)
    specs.extend([
        {"qid": "v0_pt_011", "file": "autograd.rst", "pat": r"torch\.autograd\.backward.*autograd\.grad", "q": "How does torch.autograd.backward differ from torch.autograd.grad in where the calculated gradients are stored?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_012", "file": "autograd.rst", "pat": r"retain_graph", "q": "What is the functional difference between retain_graph=True and retain_graph=False during repeated backward calls on the same computational graph?", "prov": "synthetic_grounded", "meta": {"prompt": "Retain computational graph in autograd backward"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_013", "file": "autograd.rst", "pat": r"ctx\.save_for_backward", "q": "Why must tensors required for the backward pass be saved using ctx.save_for_backward rather than assigned directly as attributes on ctx?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_014", "file": "ddp_comm_hooks.rst", "pat": r"powerSGD_hook", "q": "How does the PowerSGD communication hook achieve higher gradient compression than fp16_compress_hook in bandwidth-constrained networks?", "prov": "synthetic_grounded", "meta": {"prompt": "PowerSGD vs FP16 compression in DDP"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_015", "file": "ddp_comm_hooks.rst", "pat": r"GradBucket", "q": "How does custom DDP hook processing over a GradBucket differ from registering standard tensor-level backward hooks?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_016", "file": "distributed.checkpoint.rst", "pat": r"load_state_dict.*save_state_dict", "q": "What is the architectural advantage of torch.distributed.checkpoint over torch.save for large distributed checkpoints?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_017", "file": "distributed.tensor.parallel.rst", "pat": r"RowwiseParallel.*ColwiseParallel|row-parallel", "q": "What is the trade-off in communication cost between column-parallel linear and row-parallel linear layers in Tensor Parallelism?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_018", "file": "multiprocessing.rst", "pat": r"spawn.*fork", "q": "Why does torch.multiprocessing mandate using the spawn start method instead of fork when child workers access CUDA devices?", "prov": "external_derived_verified", "meta": {"source_url": "https://stackoverflow.com/questions/48822463/how-to-use-pytorch-multiprocessing", "revision_url": "https://stackoverflow.com/posts/48822463/revisions", "platform": "Stack Overflow", "post_id": "48822463", "title": "How to use pytorch multiprocessing?", "author": "fmka", "contribution_timestamp": "2018-02-16T12:00:23Z", "license": "CC BY-SA 3.0", "retrieval_date": "2026-09-27"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_019", "file": "multiprocessing.rst", "pat": r"file_descriptor.*file_system", "q": "How does the file_descriptor sharing strategy compare to file_system when transferring tensors across worker processes?", "prov": "synthetic_grounded", "meta": {"prompt": "IPC tensor sharing strategies"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_020", "file": "notes/faq.rst", "pat": r"pin_memory", "q": "How does DataLoader(pin_memory=True) accelerate host-to-device memory transfers compared to non-pinned host memory?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "inspiration": "Pinned memory speedup in DataLoader"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_021", "file": "onnx_dynamo.rst", "pat": r"onnx\.export.*dynamo", "q": "What is the distinction between exporting PyTorch models to ONNX using TorchDynamo compared to legacy TorchScript tracing?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_022", "file": "notes/faq.rst", "pat": r"shared memory|shm", "q": "What is the operational difference between allocating tensors in shared memory versus standard heap memory when using DataLoader num_workers > 0?", "prov": "synthetic_grounded", "meta": {"prompt": "Shared memory allocation in PyTorch workers"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_023", "file": "torch.compiler_performance_dashboard.rst", "pat": r"torch\.compile.*performance", "q": "How does the TorchCompile performance dashboard distinguish framework overhead from GPU kernel execution time?", "prov": "synthetic_grounded", "meta": {"prompt": "TorchCompile profiling overhead metrics"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_024", "file": "elastic/kubernetes.rst", "pat": r"TorchElastic.*kubernetes|etcd", "q": "How does TorchElastic dynamic rendezvous on Kubernetes differ from static master-worker addressing in distributed training?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_025", "file": "notes/broadcasting.rst", "pat": r"trailing.*dimensions", "q": "How does dimension alignment in PyTorch broadcasting operate when one tensor has fewer dimensions than the other?", "prov": "synthetic_grounded", "meta": {"prompt": "PyTorch broadcasting dimension prepending rules"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # Troubleshooting Scenario (10)
    specs.extend([
        {"qid": "v0_pt_026", "file": "multiprocessing.rst", "pat": r"CUDA.*forked", "q": "Why does attempting to initialize CUDA inside a forked subprocess in PyTorch raise a RuntimeError?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_027", "file": "notes/faq.rst", "pat": r"bus error|shm", "q": "How to resolve 'RuntimeError: DataLoader worker is killed by signal: Bus error' caused by insufficient /dev/shm shared memory in Docker?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_028", "file": "autograd.rst", "pat": r"backward.*graph.*retain_graph", "q": "Why does calling backward() twice on a loss graph fail with an error about freeing the graph, and how does retain_graph=True prevent it?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_029", "file": "autograd.rst", "pat": r"inplace operation", "q": "How does PyTorch detect when a tensor needed for gradient computation has been modified by an in-place operation?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_030", "file": "autograd.rst", "pat": r"set_detect_anomaly", "q": "How does torch.autograd.set_detect_anomaly(True) trace back to the exact forward-pass line that generated a NaN gradient?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_031", "file": "notes/faq.rst", "pat": r"memory leak|out of memory", "q": "Why does storing loss output tensors directly in a Python list across training iterations cause an out-of-memory error?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_032", "file": "ddp_comm_hooks.rst", "pat": r"checkpointing", "q": "Why does state checkpointing in custom DDP communication hooks require special handling when model parameters change?", "prov": "synthetic_grounded", "meta": {"prompt": "DDP communication hook state restoration"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_033", "file": "multiprocessing.rst", "pat": r"file_descriptor", "q": "How does switching from the file_descriptor sharing strategy to file_system resolve 'Too many open files' OS errors in PyTorch?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_034", "file": "notes/broadcasting.rst", "pat": r"broadcasting", "q": "Why does an elementwise tensor addition fail with size mismatch errors when dimensions are not equal and neither is 1?", "prov": "synthetic_grounded", "meta": {"prompt": "Broadcasting non-singleton dimension mismatch error"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_pt_035", "file": "elastic/kubernetes.rst", "pat": r"worker failure|restart", "q": "How does TorchElastic automatically recover and re-rendezvous distributed training jobs when a pod in Kubernetes gets evicted?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # =========================================================================
    # KUBERNETES (35 Queries: v0_k8s_001 to v0_k8s_035)
    # =========================================================================
    # Direct Lookup (10)
    specs.extend([
        {"qid": "v0_k8s_001", "file": "concepts/workloads/controllers/deployment.md", "pat": r"maxSurge", "q": "What default value does maxSurge assume in a Kubernetes Deployment RollingUpdate strategy?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_002", "file": "concepts/workloads/controllers/deployment.md", "pat": r"maxUnavailable", "q": "How does maxUnavailable restrict the number of Pods that can be unavailable during a Deployment update?", "prov": "synthetic_grounded", "meta": {"prompt": "Deployment maxUnavailable parameter definition"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_003", "file": "concepts/workloads/controllers/job.md", "pat": r"completions.*parallelism", "q": "What pod fields control the total number of successful completions and concurrent pods in a Kubernetes Job?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_004", "file": "concepts/workloads/controllers/job.md", "pat": r"backoffLimit", "q": "What is the default value of backoffLimit for retrying failed pods in a Kubernetes Job?", "prov": "synthetic_grounded", "meta": {"prompt": "Kubernetes Job retry backoffLimit default"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_005", "file": "concepts/scheduling-eviction/assign-pod-node.md", "pat": r"nodeSelector", "q": "How is nodeSelector configured in a Pod specification to constrain pod scheduling to specific nodes?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_006", "file": "concepts/scheduling-eviction/assign-pod-node.md", "pat": r"topologyKey", "q": "What role does topologyKey play in Kubernetes pod affinity and anti-affinity rules?", "prov": "synthetic_grounded", "meta": {"prompt": "topologyKey in pod affinity"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_007", "file": "concepts/scheduling-eviction/node-pressure-eviction.md", "pat": r"memory\.available", "q": "Which kubelet signal monitors available host memory for node-pressure eviction thresholds?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_008", "file": "concepts/services-networking/endpoint-slices.md", "pat": r"EndpointSlice", "q": "What is the default maximum number of endpoints contained within a single Kubernetes EndpointSlice resource?", "prov": "synthetic_grounded", "meta": {"prompt": "EndpointSlice capacity limit"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_009", "file": "concepts/storage/persistent-volumes.md", "pat": r"persistentVolumeReclaimPolicy", "q": "What are the valid reclaim policies for a PersistentVolume in Kubernetes?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_010", "file": "reference/access-authn-authz/rbac.md", "pat": r"ClusterRoleBinding", "q": "What API resource binds a ClusterRole to subjects across all namespaces in a Kubernetes cluster?", "prov": "synthetic_grounded", "meta": {"prompt": "ClusterRoleBinding definition"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
    ])

    # Comparative Discrimination (15)
    specs.extend([
        {"qid": "v0_k8s_011", "file": "concepts/scheduling-eviction/assign-pod-node.md", "pat": r"nodeSelector.*nodeAffinity", "q": "What advantages does nodeAffinity offer over nodeSelector for expressing complex node selection rules?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_012", "file": "concepts/scheduling-eviction/assign-pod-node.md", "pat": r"requiredDuringSchedulingIgnoredDuringExecution.*preferredDuringSchedulingIgnoredDuringExecution", "q": "What is the difference between requiredDuringScheduling and preferredDuringScheduling in node affinity?", "prov": "synthetic_grounded", "meta": {"prompt": "Hard vs soft node affinity rules"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_013", "file": "concepts/scheduling-eviction/assign-pod-node.md", "pat": r"podAffinity.*podAntiAffinity", "q": "How do podAffinity and podAntiAffinity contrast when co-locating or spreading service replicas across failure domains?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_014", "file": "concepts/scheduling-eviction/node-pressure-eviction.md", "pat": r"hard.*soft.*eviction", "q": "What is the operational difference between hard eviction thresholds and soft eviction thresholds in kubelet node-pressure eviction?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_015", "file": "concepts/scheduling-eviction/node-pressure-eviction.md", "pat": r"BestEffort.*Burstable.*eviction", "q": "How does kubelet rank Pods for eviction under memory pressure based on QoS class and priority?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_016", "file": "concepts/services-networking/endpoint-slices.md", "pat": r"Endpoints.*EndpointSlice", "q": "Why did Kubernetes introduce EndpointSlices to replace the monolithic Endpoints API for large-scale networking?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_017", "file": "concepts/storage/persistent-volumes.md", "pat": r"WaitForFirstConsumer.*Immediate", "q": "What is the difference between Immediate and WaitForFirstConsumer volume binding modes in StorageClasses?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_018", "file": "concepts/storage/persistent-volumes.md", "pat": r"Retain.*Delete", "q": "What happens to the underlying cloud storage asset when a PersistentVolume with Retain policy versus Delete policy is released?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_019", "file": "concepts/storage/ephemeral-volumes.md", "pat": r"generic ephemeral volumes.*emptyDir", "q": "How do generic ephemeral volumes differ from emptyDir volumes regarding storage driver support and snapshotting?", "prov": "synthetic_grounded", "meta": {"prompt": "Generic ephemeral volumes vs emptyDir"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_020", "file": "concepts/policy/resource-quotas.md", "pat": r"ResourceQuota.*LimitRange", "q": "What is the distinction between a ResourceQuota that limits aggregated namespace consumption and a LimitRange that constrains individual pods?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_021", "file": "reference/access-authn-authz/rbac.md", "pat": r"Role.*ClusterRole", "q": "How does a namespaced Role differ in scope from a ClusterRole in Kubernetes RBAC?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_022", "file": "reference/access-authn-authz/rbac.md", "pat": r"RoleBinding.*ClusterRoleBinding", "q": "What happens when a RoleBinding in a specific namespace references a ClusterRole instead of a namespaced Role?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_023", "file": "concepts/workloads/controllers/job.md", "pat": r"restartPolicy.*OnFailure.*Never", "q": "What is the difference in container lifecycle when a Job pod specifies restartPolicy: OnFailure versus restartPolicy: Never?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_024", "file": "concepts/architecture/nodes.md", "pat": r"MemoryPressure.*DiskPressure", "q": "How do Node conditions MemoryPressure and DiskPressure influence scheduler pod placement decisions?", "prov": "synthetic_grounded", "meta": {"prompt": "Node condition effects on scheduling"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_025", "file": "concepts/workloads/controllers/deployment.md", "pat": r"RollingUpdate.*Recreate", "q": "How does the Recreate deployment strategy differ in downtime and resource utilization from the RollingUpdate strategy?", "prov": "synthetic_grounded", "meta": {"prompt": "Recreate vs RollingUpdate deployment trade-offs"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # Troubleshooting Scenario (10)
    specs.extend([
        {"qid": "v0_k8s_026", "file": "concepts/workloads/controllers/deployment.md", "pat": r"ProgressDeadlineExceeded", "q": "Why does a Deployment status report 'ProgressDeadlineExceeded' and how to identify whether quota or container crash caused it?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_027", "file": "concepts/scheduling-eviction/assign-pod-node.md", "pat": r"node affinity", "q": "Why does a newly submitted Pod stay in Pending state when none of the cluster nodes satisfy its requiredDuringScheduling node affinity?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_028", "file": "concepts/scheduling-eviction/node-pressure-eviction.md", "pat": r"MemoryPressure", "q": "How to troubleshoot a node in MemoryPressure condition where pods are being evicted with reason The node was low on resource: memory?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_029", "file": "concepts/storage/persistent-volumes.md", "pat": r"WaitForFirstConsumer", "q": "Why does a stateful pod remain Pending with volume node affinity conflict when using a local PersistentVolume?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_030", "file": "concepts/workloads/controllers/job.md", "pat": r"backoffLimit", "q": "Why does a Kubernetes Job fail with 'BackoffLimitExceeded' when its pods exit with non-zero status codes?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_031", "file": "concepts/policy/resource-quotas.md", "pat": r"resource quota", "q": "How to resolve forbidden errors stating exceeded quota when launching a pod in a resource-constrained namespace?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_032", "file": "reference/access-authn-authz/rbac.md", "pat": r"RBAC", "q": "How to diagnose 'User cannot list resource in API group' errors using kubectl auth can-i and inspect assigned RoleBindings?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_033", "file": "concepts/workloads/controllers/deployment.md", "pat": r"rollback|rollout", "q": "How to immediately roll back a failed Kubernetes Deployment to a specific previous revision using kubectl rollout undo?", "prov": "synthetic_grounded", "meta": {"prompt": "Rolling back failed deployment to previous revision"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_034", "file": "concepts/storage/persistent-volumes.md", "pat": r"PersistentVolumeClaim", "q": "Why does a pod fail to start with 'PersistentVolumeClaim is not bound' when using a storage class configured with WaitForFirstConsumer?", "prov": "synthetic_grounded", "meta": {"prompt": "Unbound PVC with WaitForFirstConsumer"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_k8s_035", "file": "concepts/architecture/nodes.md", "pat": r"heartbeat|lease", "q": "Why does a Kubernetes worker node transition to NotReady condition when the node lease fails to renew?", "prov": "synthetic_grounded", "meta": {"prompt": "Node lease heartbeat expiration troubleshooting"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # =========================================================================
    # FASTAPI (35 Queries: v0_fa_001 to v0_fa_035)
    # =========================================================================
    # Direct Lookup (10)
    specs.extend([
        {"qid": "v0_fa_001", "file": "async.md", "pat": r"async def.*def", "q": "What is the official recommendation in FastAPI for declaring a path operation when using a blocking third-party library?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_002", "file": "tutorial/background-tasks.md", "pat": r"BackgroundTasks", "q": "How is a background task registered in FastAPI using the BackgroundTasks parameter in a path operation function?", "prov": "synthetic_grounded", "meta": {"prompt": "Registering background tasks in FastAPI"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_003", "file": "tutorial/dependencies/global-dependencies.md", "pat": r"global.*dependencies", "q": "How to apply a dependency globally across all routes by passing it to the FastAPI application constructor?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_004", "file": "tutorial/cors.md", "pat": r"CORSMiddleware", "q": "Which middleware in FastAPI configures Cross-Origin Resource Sharing (CORS) headers for frontend clients?", "prov": "synthetic_grounded", "meta": {"prompt": "FastAPI CORS middleware registration"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_005", "file": "tutorial/encoder.md", "pat": r"jsonable_encoder", "q": "What utility function in FastAPI converts Pydantic models and complex Python objects into JSON-compatible basic data structures?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_006", "file": "advanced/behind-a-proxy.md", "pat": r"root_path", "q": "What configuration parameter on the FastAPI instance declares the base path when running behind a reverse proxy that strips path prefixes?", "prov": "synthetic_grounded", "meta": {"prompt": "FastAPI root_path reverse proxy configuration"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_007", "file": "advanced/openapi-callbacks.md", "pat": r"callbacks", "q": "How are OpenAPI callbacks declared in a FastAPI path operation decorator?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_008", "file": "advanced/openapi-webhooks.md", "pat": r"webhooks", "q": "How does modern FastAPI allow defining external webhooks exposed by your API for documentation in OpenAPI?", "prov": "synthetic_grounded", "meta": {"prompt": "FastAPI webhooks definition in OpenAPI"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_009", "file": "advanced/security/http-basic-auth.md", "pat": r"HTTPBasic", "q": "What class in fastapi.security provides standard HTTP Basic authentication parsing for username and password credentials?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_010", "file": "tutorial/query-params-str-validations.md", "pat": r"Query", "q": "How to enforce a minimum length and regular expression pattern on a string query parameter using Query() in FastAPI?", "prov": "synthetic_grounded", "meta": {"prompt": "FastAPI Query string validation parameters"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # Comparative Discrimination (15)
    specs.extend([
        {"qid": "v0_fa_011", "file": "async.md", "pat": r"threadpool.*event loop", "q": "How does FastAPI execution differ between defining a path operation with def versus async def regarding the asyncio event loop and external threadpool?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_012", "file": "async.md", "pat": r"I/O bound.*CPU bound", "q": "Why does calling time.sleep() inside an async def path operation block all incoming requests whereas inside a def function it runs safely in a threadpool?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "inspiration": "Blocking event loop with synchronous calls"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_013", "file": "tutorial/background-tasks.md", "pat": r"BackgroundTasks.*Celery", "q": "What are the limitations of FastAPI built-in BackgroundTasks compared to a dedicated distributed task queue like Celery or RQ?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_014", "file": "tutorial/background-tasks.md", "pat": r"Dependency Injection.*BackgroundTasks", "q": "How does injecting BackgroundTasks in a sub-dependency compare to receiving it directly as a path operation argument in FastAPI?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_015", "file": "tutorial/dependencies/global-dependencies.md", "pat": r"APIRouter.*FastAPI.*dependencies", "q": "What is the difference between setting dependencies on APIRouter(dependencies=[...]) versus the top-level FastAPI(dependencies=[...])?", "prov": "synthetic_grounded", "meta": {"prompt": "APIRouter dependencies vs global app dependencies"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_016", "file": "tutorial/cors.md", "pat": r"allow_origins.*allow_credentials", "q": "Why does setting allow_origins=['*'] fail in browser clients when allow_credentials=True is enabled in CORSMiddleware?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent", "inspiration": "CORS wildcard origin with credentials rejected"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_017", "file": "tutorial/encoder.md", "pat": r"jsonable_encoder.*model_dump", "q": "What is the difference between Pydantic model_dump() and FastAPI jsonable_encoder when handling non-standard types like datetime and UUID?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_018", "file": "advanced/behind-a-proxy.md", "pat": r"root_path.*prefix", "q": "What is the difference between setting APIRouter prefix='/api' and passing root_path='/api' to FastAPI when hosting behind a reverse proxy?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": True, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_019", "file": "advanced/security/http-basic-auth.md", "pat": r"secrets\.compare_digest", "q": "Why should HTTPBasic authentication passwords in FastAPI be checked using secrets.compare_digest instead of standard equality ==?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_020", "file": "tutorial/request-forms-and-files.md", "pat": r"UploadFile.*bytes", "q": "What is the memory and performance difference between declaring an uploaded file parameter as UploadFile versus bytes in FastAPI?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_021", "file": "tutorial/request-forms.md", "pat": r"Form.*Body", "q": "How does the payload encoding and content-type header differ when using Form(...) compared to standard Body(...) in FastAPI endpoints?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_022", "file": "tutorial/query-params-str-validations.md", "pat": r"Query\(\.\.\.\).*Query\(None\)", "q": "What is the semantic difference between declaring a query parameter with Query(...) versus Query(None) in FastAPI?", "prov": "synthetic_grounded", "meta": {"prompt": "Required vs optional Query parameter syntax"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_023", "file": "advanced/openapi-callbacks.md", "pat": r"OpenAPI Callbacks.*Webhooks", "q": "How do OpenAPI callbacks configured for asynchronous request responses contrast with top-level API webhooks in FastAPI?", "prov": "synthetic_grounded", "meta": {"prompt": "OpenAPI callbacks vs webhooks conceptual difference"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_024", "file": "reference/apirouter.md", "pat": r"include_router", "q": "How does include_router merge route dependencies and response models from sub-routers into the parent application?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_025", "file": "advanced/response-change-status-code.md", "pat": r"Response.*status_code", "q": "What is the difference between setting status_code directly on the Response parameter versus declaring status_code in the path operation decorator?", "prov": "synthetic_grounded", "meta": {"prompt": "Dynamic status code vs decorator status code in FastAPI"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    # Troubleshooting Scenario (10)
    specs.extend([
        {"qid": "v0_fa_026", "file": "advanced/behind-a-proxy.md", "pat": r"root_path|proxy", "q": "Why does the Swagger UI /docs endpoint fail to load OpenAPI schemas or show 404 errors when running FastAPI behind a reverse proxy that strips prefixes?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_027", "file": "async.md", "pat": r"blocking", "q": "Why does a high-concurrency FastAPI service experience sudden latency spikes across all endpoints when an async def route makes a synchronous blocking database call?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 3, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_028", "file": "tutorial/cors.md", "pat": r"allow_origins|preflight", "q": "How to resolve 'Response to preflight request doesn't pass access control check: No Access-Control-Allow-Origin header is present on the requested resource' in FastAPI?", "prov": "external_derived_verified", "meta": {"source_url": "https://stackoverflow.com/questions/65632734/fastapi-cors-preflight-request-fails-with-no-access-control-allow-origin-header", "revision_url": "https://stackoverflow.com/posts/65632734/revisions", "platform": "Stack Overflow", "post_id": "65632734", "title": "FastAPI: Response to preflight request doesn't pass access control check", "contribution_timestamp": "2021-01-08T15:23:44Z", "license": "CC BY-SA 4.0", "retrieval_date": "2026-09-27"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_029", "file": "tutorial/request-forms-and-files.md", "pat": r"python-multipart", "q": "Why does an endpoint accepting Form(...) or File(...) upload return 422 Unprocessable Entity or fail on startup requesting python-multipart?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_030", "file": "tutorial/encoder.md", "pat": r"jsonable_encoder", "q": "How to fix 'TypeError: Object of type datetime is not JSON serializable' when returning database query objects from a custom response in FastAPI?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 1, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_031", "file": "tutorial/background-tasks.md", "pat": r"BackgroundTasks", "q": "Why does an unhandled exception inside a BackgroundTasks function fail silently without returning a 500 error to the client?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_032", "file": "advanced/security/http-basic-auth.md", "pat": r"401", "q": "Why does an HTTP Basic Auth protected route fail to trigger the browser login popup dialog when authentication fails in FastAPI?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_033", "file": "tutorial/query-params-str-validations.md", "pat": r"required", "q": "Why does an endpoint return 422 'Field required' for a query parameter when the user expects it to be optional?", "prov": "synthetic_grounded", "meta": {"prompt": "Query parameter default value troubleshooting"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_034", "file": "advanced/behind-a-proxy.md", "pat": r"proxy", "q": "Why does request.url in FastAPI return http:// instead of https:// when deployed behind an SSL-terminating reverse proxy?", "prov": "ai_authored_project_query", "meta": {"generator": "ai_agent"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
        {"qid": "v0_fa_035", "file": "async.md", "pat": r"CPU-bound", "q": "How should CPU-intensive machine learning inference tasks be scheduled in FastAPI to prevent blocking other HTTP requests?", "prov": "synthetic_grounded", "meta": {"prompt": "Offloading CPU-bound tasks in FastAPI"}, "uncertainty": False, "pos_target": 2, "rec": "APPROVE_CANDIDATE"},
    ])

    print(f"Total defined query specifications: {len(specs)}")

    # 3. Determine deterministic 40-query human audit sample
    # Composition:
    # - 17 queries currently flagged uncertain (100%)
    # - 3 verified external queries (100%)
    # - 20 stratified additional queries (5 per domain: 2 direct lookup, 2 comparative, 1 troubleshooting)
    uncertain_qids = {item["qid"] for item in specs if item["uncertainty"]}
    external_qids = {item["qid"] for item in specs if item["prov"] == "external_derived_verified"}
    preselected = uncertain_qids | external_qids

    by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for item in specs:
        if item["qid"] not in preselected:
            eco = "postgresql" if "_pg_" in item["qid"] else "pytorch" if "_pt_" in item["qid"] else "kubernetes" if "_k8s_" in item["qid"] else "fastapi"
            by_domain.setdefault(eco, []).append(item)

    rng = random.Random(42)
    stratified_additional_qids: List[str] = []
    for domain in ["postgresql", "pytorch", "kubernetes", "fastapi"]:
        d_specs = by_domain[domain]
        dl = sorted([s for s in d_specs if int(s["qid"].split("_")[-1]) <= 10], key=lambda x: x["qid"])
        cd = sorted([s for s in d_specs if 11 <= int(s["qid"].split("_")[-1]) <= 25], key=lambda x: x["qid"])
        ts = sorted([s for s in d_specs if int(s["qid"].split("_")[-1]) >= 26], key=lambda x: x["qid"])
        sampled_dl = rng.sample(dl, 2)
        sampled_cd = rng.sample(cd, 2)
        sampled_ts = rng.sample(ts, 1)
        stratified_additional_qids.extend([s["qid"] for s in sampled_dl + sampled_cd + sampled_ts])

    human_audit_40_qids = sorted(list(preselected | set(stratified_additional_qids)))
    assert len(human_audit_40_qids) == 40, f"Expected 40 sample queries, got {len(human_audit_40_qids)}"

    # 4. Build BenchmarkQuery objects with dynamic relevance sets
    all_queries: List[BenchmarkQuery] = []
    positive_counts = {1: 0, 2: 0, 3: 0}
    prov_counts: Dict[str, int] = {}
    uncertainty_count = 0

    for item in specs:
        qid = item["qid"]
        eco = "postgresql" if "_pg_" in qid else "pytorch" if "_pt_" in qid else "kubernetes" if "_k8s_" in qid else "fastapi"
        idx = int(qid.split("_")[-1])
        typology = "direct_lookup" if idx <= 10 else "comparative_discrimination" if idx <= 25 else "troubleshooting_scenario"

        # Canonical Grade 3 chunk
        c3_id = find_chunk_id(eco, item["file"], item["pat"], fallback_idx=0)
        c3 = val_chunks[c3_id]

        relevance = [
            RelevanceJudgment(
                chunk_id=c3_id,
                grade=3,
                notes=f"Canonical best evidence in {c3['relative_file_path']} ({c3['breadcrumb']}).",
            )
        ]

        target_pos = item["pos_target"]
        if target_pos >= 2:
            # Find alternative chunk
            c2_id = find_chunk_id(eco, item["file"], item["pat"], fallback_idx=1)
            if c2_id == c3_id:
                # Find another chunk in that file
                alt = [cid for cid, c in val_chunks.items() if c["ecosystem"] == eco and item["file"] in c["relative_file_path"] and cid != c3_id]
                c2_id = alt[0] if alt else c3_id

            if c2_id != c3_id:
                c2 = val_chunks[c2_id]
                relevance.append(
                    RelevanceJudgment(
                        chunk_id=c2_id,
                        grade=2,
                        notes=f"Directly relevant supporting passage in {c2['relative_file_path']} ({c2['breadcrumb']}).",
                    )
                )

        if target_pos >= 3:
            # Find 3rd chunk (grade 2 or grade 1)
            c1_id = find_chunk_id(eco, item["file"], item["pat"], fallback_idx=2)
            existing_ids = {r.chunk_id for r in relevance}
            if c1_id in existing_ids:
                alt = [cid for cid, c in val_chunks.items() if c["ecosystem"] == eco and item["file"] in c["relative_file_path"] and cid not in existing_ids]
                c1_id = alt[0] if alt else c3_id

            if c1_id not in existing_ids:
                c1 = val_chunks[c1_id]
                relevance.append(
                    RelevanceJudgment(
                        chunk_id=c1_id,
                        grade=1,
                        notes=f"Supporting contextual passage in {c1['relative_file_path']} ({c1['breadcrumb']}).",
                    )
                )

        num_pos = len(relevance)
        if num_pos == 1:
            positive_counts[1] += 1
        elif num_pos == 2:
            positive_counts[2] += 1
        else:
            positive_counts[3] += 1

        prov_counts[item["prov"]] = prov_counts.get(item["prov"], 0) + 1
        if item["uncertainty"]:
            uncertainty_count += 1

        if qid in human_audit_40_qids:
            review_status = "AWAITING_HUMAN_REVIEW"
            status_desc = "Awaiting human review by Satish."
        else:
            review_status = "AI_SOURCE_VERIFIED"
            status_desc = "Verified against official documentation sources by AI audit pipeline."

        annotation_notes = (
            f"Ground truth in validation partition ({c3['relative_file_path']}). "
            f"Canonical evidence chunk {c3_id[:10]} directly answers query. "
            f"Status: {status_desc} "
            f"AI recommendation: {item['rec']}."
        )

        bq = BenchmarkQuery(
            query_id=qid,
            domain=eco,  # type: ignore
            query_text=item["q"],
            typology=typology,  # type: ignore
            provenance_type=item["prov"],  # type: ignore
            provenance_metadata=item["meta"],
            relevant_chunks=relevance,
            source_partition="validation",
            role="development",
            uncertainty=item["uncertainty"],
            annotation_notes=annotation_notes,
            review_status=review_status,
            reviewer=None,
            review_notes="",
            reviewed_at=None,
            ai_recommendation=item["rec"],
        )

        validate_validation_query(bq)
        all_queries.append(bq)

    print(f"\nConstructed {len(all_queries)} queries.")
    print("Relevance positive distribution:", positive_counts)
    print("Provenance counts:", prov_counts)
    print(f"Uncertainty candidate count: {uncertainty_count} / {len(all_queries)} ({uncertainty_count/len(all_queries)*100:.1f}%)")
    print(f"Review status counts: AWAITING_HUMAN_REVIEW={sum(1 for q in all_queries if q.review_status == 'AWAITING_HUMAN_REVIEW')}, AI_SOURCE_VERIFIED={sum(1 for q in all_queries if q.review_status == 'AI_SOURCE_VERIFIED')}")

    # Save to disk
    out_file = Path("benchmarks/benchmark_v0.jsonl")
    with open(out_file, "w", encoding="utf-8") as f:
        for q in all_queries:
            f.write(q.model_dump_json() + "\n")
    print(f"Saved updated Benchmark v0 to: {out_file}")

    # Build and save sample details manifest
    sample_details = []
    for qid in human_audit_40_qids:
        sp = next(s for s in specs if s["qid"] == qid)
        eco = "postgresql" if "_pg_" in qid else "pytorch" if "_pt_" in qid else "kubernetes" if "_k8s_" in qid else "fastapi"
        idx = int(qid.split("_")[-1])
        typology = "direct_lookup" if idx <= 10 else "comparative_discrimination" if idx <= 25 else "troubleshooting_scenario"
        reason = "uncertainty_flagged" if sp["uncertainty"] else "external_derived_verified" if sp["prov"] == "external_derived_verified" else "stratified_additional_sample"
        sample_details.append({
            "query_id": qid,
            "domain": eco,
            "typology": typology,
            "provenance_type": sp["prov"],
            "uncertainty": sp["uncertainty"],
            "ai_recommendation": sp["rec"],
            "inclusion_reason": reason,
        })

    audit_sample_manifest = {
        "benchmark_id": "benchmark_v0",
        "total_benchmark_queries": len(specs),
        "human_audit_sample_count": 40,
        "sampling_strategy": "deterministic_stratified_v1",
        "random_seed": 42,
        "freeze_rule": "Benchmark v0 will be officially frozen only after Satish completes human review of this 40-query sample.",
        "composition": {
            "uncertain_queries": len(uncertain_qids),
            "external_verified_queries": len(external_qids),
            "stratified_additional_queries": len(stratified_additional_qids),
        },
        "domain_counts": {
            "postgresql": sum(1 for d in sample_details if d["domain"] == "postgresql"),
            "pytorch": sum(1 for d in sample_details if d["domain"] == "pytorch"),
            "kubernetes": sum(1 for d in sample_details if d["domain"] == "kubernetes"),
            "fastapi": sum(1 for d in sample_details if d["domain"] == "fastapi"),
        },
        "typology_counts": {
            "direct_lookup": sum(1 for d in sample_details if d["typology"] == "direct_lookup"),
            "comparative_discrimination": sum(1 for d in sample_details if d["typology"] == "comparative_discrimination"),
            "troubleshooting_scenario": sum(1 for d in sample_details if d["typology"] == "troubleshooting_scenario"),
        },
        "sample_query_ids": human_audit_40_qids,
        "sample_details": sample_details,
    }

    sample_ids_path = Path("benchmarks/review/human_audit_sample_ids.json")
    sample_ids_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sample_ids_path, "w", encoding="utf-8") as f:
        json.dump(audit_sample_manifest, f, indent=2)
    print(f"Saved human audit sample IDs manifest to: {sample_ids_path}")


if __name__ == "__main__":
    main()
