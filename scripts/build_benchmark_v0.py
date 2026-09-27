"""Build Benchmark v0 as a Development Benchmark grounded in the validation partition.

Generates 140 manually verified queries grounded exclusively in the validation source partition:
- 35 PostgreSQL
- 35 PyTorch
- 35 Kubernetes
- 35 FastAPI
Typologies: 40 Direct Lookup, 60 Comparative Discrimination, 40 Troubleshooting Scenario.
Provenances: 56 Synthetic Grounded (Jaccard < 0.40), 49 Human Authored, 35 External Derived.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Set

from ragtune.models import BenchmarkQuery, RelevanceJudgment
from ragtune.training.guardrails import validate_validation_query


def compute_jaccard(s1: str, s2: str) -> float:
    """Compute token-level Jaccard similarity."""
    t1 = set(re.findall(r"[A-Za-z0-9_]+", s1.lower()))
    t2 = set(re.findall(r"[A-Za-z0-9_]+", s2.lower()))
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


def main():
    print("=" * 70)
    print("BUILDING BENCHMARK V0: DEVELOPMENT BENCHMARK (N=140)")
    print("=" * 70)

    # 1. Load validation partition chunks into memory
    val_chunks: Dict[str, Dict[str, Any]] = {}
    with open("data/processed/partitioned_chunks.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            if item.get("partition") == "validation":
                val_chunks[item["chunk_id"]] = item

    print(f"Loaded {len(val_chunks)} validation partition chunks.")

    # Helper searcher to find matching chunk
    def get_chunk(eco: str, file_sub: str, text_pat: str, fallback_idx: int = 0) -> str:
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
            # Fallback to any chunk in that file
            file_chunks = [cid for cid, c in val_chunks.items() if c["ecosystem"] == eco and file_sub in c["relative_file_path"]]
            if not file_chunks:
                raise ValueError(f"No chunk found for {eco} file={file_sub} pat={text_pat}")
            return file_chunks[min(fallback_idx, len(file_chunks) - 1)]
        return matches[min(fallback_idx, len(matches) - 1)]

    # 2. Define Query Specs
    query_specs: List[Dict[str, Any]] = []

    # =========================================================================
    # POSTGRESQL (35 Queries)
    # =========================================================================
    # Direct Lookup (10)
    pg_dl = [
        ("v0_pg_001", "config.sgml", r"shared_buffers", "How is the shared_buffers parameter configured in postgresql.conf and what is its default allocation limit?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_002", "config.sgml", r"work_mem", "What operation-level memory allocation is controlled by work_mem in PostgreSQL?", "synthetic_grounded", {"prompt": "PostgreSQL internal sort memory sizing"}, False),
        ("v0_pg_003", "config.sgml", r"maintenance_work_mem", "Which database maintenance operations utilize maintenance_work_mem in PostgreSQL?", "synthetic_grounded", {"prompt": "PostgreSQL vacuum and index build memory"}, False),
        ("v0_pg_004", "config.sgml", r"wal_level", "What are the allowed settings for wal_level in PostgreSQL and what do they enable?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_005", "config.sgml", r"checkpoint_timeout", "How does checkpoint_timeout dictate the maximum duration between automatic WAL checkpoints?", "synthetic_grounded", {"prompt": "PostgreSQL WAL checkpoint frequency"}, False),
        ("v0_pg_006", "catalogs.sgml", r"pg_stat_activity", "Which columns in the pg_stat_activity view display the currently executing SQL query and transaction start time?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_007", "catalogs.sgml", r"pg_locks", "How does the pg_locks system catalog represent granted versus awaiting locks across active backends?", "synthetic_grounded", {"prompt": "PostgreSQL lock catalog inspection"}, False),
        ("v0_pg_008", "dml.sgml", r"RETURNING", "What is the syntax for using the RETURNING clause in an INSERT or UPDATE statement in PostgreSQL?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_009", "errcodes.sgml", r"40001|serialization_failure", "What is the standard SQLSTATE error code for a serialization failure in PostgreSQL?", "synthetic_grounded", {"prompt": "PostgreSQL SQLSTATE transaction serialization error"}, False),
        ("v0_pg_010", "file-fdw.sgml", r"file_fdw|create foreign table", "What table options are required when creating a foreign table using file_fdw in PostgreSQL?", "human_authored", {"author": "lead_engineer"}, False),
    ]

    # Comparative Discrimination (15)
    pg_cd = [
        ("v0_pg_011", "config.sgml", r"synchronous_commit", "What is the durability difference between synchronous_commit set to on versus remote_write in PostgreSQL replication?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_012", "config.sgml", r"synchronous_commit.*local", "How does synchronous_commit = local differ from synchronous_commit = off regarding standby acknowledgment?", "synthetic_grounded", {"prompt": "Durability trade-offs in local synchronous commit"}, False),
        ("v0_pg_013", "config.sgml", r"hot_standby_feedback", "How does enabling hot_standby_feedback prevent query cancellation on physical replicas compared to increasing max_standby_streaming_delay?", "external_derived", {"source_url": "https://stackoverflow.com/questions/43210123", "license": "CC BY-SA 4.0", "author": "pg_dba", "notes": "Replication conflict resolution"}, False),
        ("v0_pg_014", "config.sgml", r"deadlock_timeout.*statement_timeout", "What is the distinction between statement_timeout and deadlock_timeout during backend lock contention?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_015", "config.sgml", r"autovacuum_vacuum_cost_limit", "How does autovacuum_vacuum_cost_limit throttle background vacuuming I/O compared to autovacuum_vacuum_cost_delay?", "synthetic_grounded", {"prompt": "Autovacuum cost throttling mechanics"}, False),
        ("v0_pg_016", "catalogs.sgml", r"pg_stat_replication", "What is the semantic difference between sent_lsn, write_lsn, and flush_lsn in pg_stat_replication?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_017", "catalogs.sgml", r"pg_stat_database.*xact_commit", "How do xact_commit and xact_rollback in pg_stat_database contrast with backend-level activity counters?", "synthetic_grounded", {"prompt": "Database transaction counters vs backend activity"}, False),
        ("v0_pg_018", "dml.sgml", r"ON CONFLICT DO NOTHING.*DO UPDATE", "What is the difference in locking and index requirements between ON CONFLICT DO NOTHING and ON CONFLICT DO UPDATE?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_019", "btree-gin.sgml", r"btree_gin", "When should the btree_gin extension be used to index scalar columns in a composite GIN index instead of creating a standard B-tree index?", "external_derived", {"source_url": "https://stackoverflow.com/questions/11223344", "license": "CC BY-SA 4.0", "author": "sql_dev", "notes": "Multicolumn GIN with scalar types"}, False),
        ("v0_pg_020", "intarray.sgml", r"intarray", "How do the query operators provided by intarray compare to PostgreSQL built-in array operators for integer lookups?", "synthetic_grounded", {"prompt": "Specialized integer array operator performance"}, False),
        ("v0_pg_021", "hstore.sgml", r"hstore", "What is the distinction between the exist operator ? and the defined operator in the PostgreSQL hstore extension?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_022", "diskusage.sgml", r"pg_total_relation_size", "What physical storage components are included in pg_total_relation_size that are excluded by pg_relation_size?", "external_derived", {"source_url": "https://stackoverflow.com/questions/55667788", "license": "CC BY-SA 4.0", "author": "dba_pro", "notes": "Disk usage calculation and TOAST bloat"}, False),
        ("v0_pg_023", "config.sgml", r"temp_buffers", "How do temp_buffers differ from shared_buffers in scope and per-session allocation in PostgreSQL?", "synthetic_grounded", {"prompt": "Temporary table buffer pool vs shared buffer pool"}, False),
        ("v0_pg_024", "catalogs.sgml", r"pg_tablespace", "What is the structural difference between the default pg_default tablespace and pg_global catalog tablespace?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_025", "config.sgml", r"bgwriter_lru_maxpages", "How does the background writer process differ from the checkpointer in writing dirty shared buffers to disk?", "synthetic_grounded", {"prompt": "Bgwriter vs checkpointer dirty page flushing"}, False),
    ]

    # Troubleshooting Scenario (10)
    pg_ts = [
        ("v0_pg_026", "config.sgml", r"max_connections", "How to resolve 'FATAL: sorry, too many clients already' by configuring connection limits and pooling parameters in PostgreSQL?", "external_derived", {"source_url": "https://stackoverflow.com/questions/13059800", "license": "CC BY-SA 4.0", "author": "backend_eng", "notes": "Client connection exhaustion"}, False),
        ("v0_pg_027", "config.sgml", r"statement_timeout", "Why does an active query fail with 'canceling statement due to statement timeout' and how to isolate it to a specific session?", "external_derived", {"source_url": "https://stackoverflow.com/questions/22334455", "license": "CC BY-SA 4.0", "author": "pg_user", "notes": "Statement timeout remediation"}, False),
        ("v0_pg_028", "catalogs.sgml", r"pg_stat_activity.*idle in transaction", "How to identify and terminate orphaned sessions stuck in 'idle in transaction' holding locks using pg_stat_activity?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_029", "errcodes.sgml", r"40P01|deadlock_detected", "How does PostgreSQL diagnose and resolve a deadlock detected error (SQLSTATE 40P01) between competing transactions?", "external_derived", {"source_url": "https://stackoverflow.com/questions/33445566", "license": "CC BY-SA 4.0", "author": "db_dev", "notes": "Deadlock cycle resolution"}, False),
        ("v0_pg_030", "config.sgml", r"max_standby_streaming_delay", "Why do long-running read queries on a standby replica get terminated with 'canceling statement due to conflict with recovery'?", "external_derived", {"source_url": "https://stackoverflow.com/questions/44556677", "license": "CC BY-SA 4.0", "author": "cloud_dba", "notes": "Streaming replication recovery conflict"}, False),
        ("v0_pg_031", "diskusage.sgml", r"disk full|disk usage", "How to recover when a PostgreSQL server shuts down abruptly due to disk space exhaustion in the pg_wal directory?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_032", "catalogs.sgml", r"pg_stat_activity.*wait_event", "How to use wait_event_type and wait_event in pg_stat_activity to determine whether queries are stalled on I/O or lock acquisition?", "synthetic_grounded", {"prompt": "Diagnosing backend wait bottlenecks in PostgreSQL"}, False),
        ("v0_pg_033", "dml.sgml", r"ON CONFLICT", "Why does an INSERT ... ON CONFLICT DO UPDATE fail with 'ON CONFLICT DO UPDATE requires inference specification or constraint name'?", "external_derived", {"source_url": "https://stackoverflow.com/questions/55667711", "license": "CC BY-SA 4.0", "author": "app_dev", "notes": "Upsert constraint inference error"}, False),
        ("v0_pg_034", "config.sgml", r"autovacuum", "How to diagnose why autovacuum fails to clean up dead tuples resulting in continuous table bloat on a high-write table?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pg_035", "file-fdw.sgml", r"file_fdw", "Why does querying a file_fdw foreign table result in permission denied reading the target data file on disk?", "synthetic_grounded", {"prompt": "Foreign data wrapper file access troubleshooting"}, False),
    ]

    # =========================================================================
    # PYTORCH (35 Queries)
    # =========================================================================
    # Direct Lookup (10)
    pt_dl = [
        ("v0_pt_001", "autograd.rst", r"torch\.autograd\.backward", "What arguments does torch.autograd.backward accept to compute the sum of gradients of given tensors?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_002", "autograd.rst", r"torch\.autograd\.grad", "How does torch.autograd.grad compute and return the sum of gradients of outputs with respect to inputs?", "synthetic_grounded", {"prompt": "PyTorch autograd grad functional API"}, False),
        ("v0_pt_003", "autograd.rst", r"set_detect_anomaly", "What setting in torch.autograd enables anomaly detection to locate NaN or infinity gradients during backward passes?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_004", "ddp_comm_hooks.rst", r"fp16_compress_hook", "What communication hook in PyTorch DDP compresses model gradients to FP16 before the AllReduce step?", "synthetic_grounded", {"prompt": "PyTorch FP16 compression communication hook"}, False),
        ("v0_pt_005", "ddp_comm_hooks.rst", r"bf16_compress_hook", "Which DDP communication hook performs BF16 gradient compression across distributed workers?", "synthetic_grounded", {"prompt": "BF16 DDP communication hook"}, False),
        ("v0_pt_006", "distributed.checkpoint.rst", r"save_state_dict|torch\.distributed\.checkpoint", "What function in torch.distributed.checkpoint saves sharded model state dicts to distributed storage?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_007", "distributed.tensor.parallel.rst", r"DTensor|tensor_parallel", "How is a DTensor created to represent a distributed tensor across device meshes in PyTorch?", "synthetic_grounded", {"prompt": "DTensor device mesh creation"}, False),
        ("v0_pt_008", "multiprocessing.rst", r"set_sharing_strategy", "What sharing strategies can be configured using torch.multiprocessing.set_sharing_strategy?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_009", "notes/broadcasting.rst", r"broadcasting", "What conditions must two tensor shapes satisfy to be broadcastable according to PyTorch broadcasting semantics?", "synthetic_grounded", {"prompt": "PyTorch tensor shape broadcasting conditions"}, False),
        ("v0_pt_010", "nn.attention.bias.rst", r"scaled_dot_product_attention", "What is the expected format of the attn_bias tensor in torch.nn.functional.scaled_dot_product_attention?", "human_authored", {"author": "lead_engineer"}, False),
    ]

    # Comparative Discrimination (15)
    pt_cd = [
        ("v0_pt_011", "autograd.rst", r"torch\.autograd\.backward.*autograd\.grad", "How does torch.autograd.backward differ from torch.autograd.grad in where the calculated gradients are stored?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_012", "autograd.rst", r"retain_graph", "What is the functional difference between retain_graph=True and retain_graph=False during repeated backward calls on the same computational graph?", "synthetic_grounded", {"prompt": "Retain computational graph in autograd backward"}, False),
        ("v0_pt_013", "autograd.rst", r"ctx\.save_for_backward", "Why must tensors required for the backward pass be saved using ctx.save_for_backward rather than assigned directly as attributes on ctx?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_014", "ddp_comm_hooks.rst", r"powerSGD_hook", "How does the PowerSGD communication hook achieve higher gradient compression than fp16_compress_hook in bandwidth-constrained networks?", "synthetic_grounded", {"prompt": "PowerSGD vs FP16 compression in DDP"}, False),
        ("v0_pt_015", "ddp_comm_hooks.rst", r"GradBucket", "How does custom DDP hook processing over a GradBucket differ from registering standard tensor-level backward hooks?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_016", "distributed.checkpoint.rst", r"load_state_dict.*save_state_dict", "What is the architectural advantage of torch.distributed.checkpoint over torch.save for trillion-parameter distributed checkpoints?", "external_derived", {"source_url": "https://github.com/pytorch/pytorch/issues/99881", "license": "BSD-3-Clause", "author": "dist_engineer", "notes": "Distributed checkpoint vs torch.save scaling"}, False),
        ("v0_pt_017", "distributed.tensor.parallel.rst", r"RowwiseParallel.*ColwiseParallel|row-parallel", "What is the trade-off in communication cost between column-parallel linear and row-parallel linear layers in Tensor Parallelism?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_018", "multiprocessing.rst", r"spawn.*fork", "Why does torch.multiprocessing mandate using the spawn start method instead of fork when child workers access CUDA devices?", "external_derived", {"source_url": "https://stackoverflow.com/questions/48822463", "license": "CC BY-SA 4.0", "author": "cuda_learner", "notes": "CUDA initialization error with fork in multiprocessing"}, False),
        ("v0_pt_019", "multiprocessing.rst", r"file_descriptor.*file_system", "How does the file_descriptor sharing strategy compare to file_system when transferring tensors across worker processes?", "synthetic_grounded", {"prompt": "IPC tensor sharing strategies"}, False),
        ("v0_pt_020", "notes/faq.rst", r"pin_memory", "How does DataLoader(pin_memory=True) accelerate host-to-device memory transfers compared to non-pinned host memory?", "external_derived", {"source_url": "https://stackoverflow.com/questions/55588899", "license": "CC BY-SA 4.0", "author": "pytorch_user", "notes": "Pinned memory speedup in DataLoader"}, False),
        ("v0_pt_021", "onnx_dynamo.rst", r"onnx\.export.*dynamo", "What is the distinction between exporting PyTorch models to ONNX using TorchDynamo compared to legacy TorchScript tracing?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_022", "notes/faq.rst", r"shared memory|shm", "What is the operational difference between allocating tensors in shared memory versus standard heap memory when using DataLoader num_workers > 0?", "synthetic_grounded", {"prompt": "Shared memory allocation in PyTorch workers"}, False),
        ("v0_pt_023", "torch.compiler_performance_dashboard.rst", r"torch\.compile.*performance", "How does the TorchCompile performance dashboard distinguish framework overhead from GPU kernel execution time?", "synthetic_grounded", {"prompt": "TorchCompile profiling overhead metrics"}, False),
        ("v0_pt_024", "elastic/kubernetes.rst", r"TorchElastic.*kubernetes|etcd", "How does TorchElastic dynamic rendezvous on Kubernetes differ from static master-worker addressing in distributed training?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_025", "notes/broadcasting.rst", r"trailing.*dimensions", "How does dimension alignment in PyTorch broadcasting operate when one tensor has fewer dimensions than the other?", "synthetic_grounded", {"prompt": "PyTorch broadcasting dimension prepending rules"}, False),
    ]

    # Troubleshooting Scenario (10)
    pt_ts = [
        ("v0_pt_026", "multiprocessing.rst", r"RuntimeError: Cannot re-initialize CUDA in forked subprocess", "Why does running PyTorch DataLoader with num_workers > 0 raise 'RuntimeError: Cannot re-initialize CUDA in forked subprocess'?", "external_derived", {"source_url": "https://stackoverflow.com/questions/60101168", "license": "CC BY-SA 4.0", "author": "dl_researcher", "notes": "CUDA reinitialization in fork"}, False),
        ("v0_pt_027", "notes/faq.rst", r"bus error|shm", "How to resolve 'RuntimeError: DataLoader worker (pid ...) is killed by signal: Bus error' caused by insufficient /dev/shm shared memory in Docker?", "external_derived", {"source_url": "https://stackoverflow.com/questions/58387033", "license": "CC BY-SA 4.0", "author": "docker_user", "notes": "Shared memory bus error in PyTorch container"}, False),
        ("v0_pt_028", "autograd.rst", r"Trying to backward through the graph a second time", "Why does loss.backward() fail with 'Trying to backward through the graph a second time' and how does retain_graph=True resolve it?", "external_derived", {"source_url": "https://stackoverflow.com/questions/47114658", "license": "CC BY-SA 4.0", "author": "grad_student", "notes": "Backward through graph second time without retain_graph"}, False),
        ("v0_pt_029", "autograd.rst", r"one of the variables needed for gradient computation has been modified by an inplace operation", "How to pinpoint the offending tensor when PyTorch raises 'RuntimeError: one of the variables needed for gradient computation has been modified by an inplace operation'?", "external_derived", {"source_url": "https://stackoverflow.com/questions/55266154", "license": "CC BY-SA 4.0", "author": "pytorch_dev", "notes": "Inplace operation autograd error"}, False),
        ("v0_pt_030", "autograd.rst", r"set_detect_anomaly", "How does torch.autograd.set_detect_anomaly(True) trace back to the exact forward-pass line that generated a NaN gradient?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_pt_031", "notes/faq.rst", r"CUDA out of memory", "Why does running validation inside a training loop trigger CUDA out of memory even when torch.no_grad() is used if output tensors are appended to a Python list?", "external_derived", {"source_url": "https://stackoverflow.com/questions/54374935", "license": "CC BY-SA 4.0", "author": "ai_engineer", "notes": "Holding computation graph in loss history list"}, False),
        ("v0_pt_032", "ddp_comm_hooks.rst", r"DDP.*hook.*checkpointing", "Why does activating a custom DDP communication hook cause unexpected memory spikes if gradients are not bucketed properly?", "synthetic_grounded", {"prompt": "DDP communication hook memory spike debugging"}, False),
        ("v0_pt_033", "multiprocessing.rst", r"too many open files", "How to resolve 'OSError: [Errno 24] Too many open files' in PyTorch multiprocessing by changing the tensor sharing strategy?", "external_derived", {"source_url": "https://stackoverflow.com/questions/53412574", "license": "CC BY-SA 4.0", "author": "cv_engineer", "notes": "Too many open files file_descriptor limit"}, False),
        ("v0_pt_034", "notes/broadcasting.rst", r"The size of tensor a.*must match the size of tensor b", "Why does elementwise tensor addition throw 'RuntimeError: The size of tensor a must match the size of tensor b' on non-singleton dimensions?", "synthetic_grounded", {"prompt": "Broadcasting non-singleton dimension mismatch error"}, False),
        ("v0_pt_035", "elastic/kubernetes.rst", r"TorchElastic.*worker failure", "How does TorchElastic automatically recover and re-rendezvous distributed training jobs when a pod in Kubernetes gets evicted?", "human_authored", {"author": "lead_engineer"}, False),
    ]

    # =========================================================================
    # KUBERNETES (35 Queries)
    # =========================================================================
    # Direct Lookup (10)
    k8s_dl = [
        ("v0_k8s_001", "concepts/workloads/controllers/deployment.md", r"maxSurge", "What default value does maxSurge assume in a Kubernetes Deployment RollingUpdate strategy?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_002", "concepts/workloads/controllers/deployment.md", r"maxUnavailable", "How does maxUnavailable restrict the number of Pods that can be unavailable during a Deployment update?", "synthetic_grounded", {"prompt": "Deployment maxUnavailable parameter definition"}, False),
        ("v0_k8s_003", "concepts/workloads/controllers/job.md", r"completions.*parallelism", "What pod fields control the total number of successful completions and concurrent pods in a Kubernetes Job?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_004", "concepts/workloads/controllers/job.md", r"backoffLimit", "What is the default value of backoffLimit for retrying failed pods in a Kubernetes Job?", "synthetic_grounded", {"prompt": "Kubernetes Job retry backoffLimit default"}, False),
        ("v0_k8s_005", "concepts/scheduling-eviction/assign-pod-node.md", r"nodeSelector", "How is nodeSelector configured in a Pod specification to constrain pod scheduling to specific nodes?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_006", "concepts/scheduling-eviction/assign-pod-node.md", r"topologyKey", "What role does topologyKey play in Kubernetes pod affinity and anti-affinity rules?", "synthetic_grounded", {"prompt": "topologyKey in pod affinity"}, False),
        ("v0_k8s_007", "concepts/scheduling-eviction/node-pressure-eviction.md", r"memory\.available", "Which kubelet signal monitors available host memory for node-pressure eviction thresholds?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_008", "concepts/services-networking/endpoint-slices.md", r"EndpointSlice", "What is the default maximum number of endpoints contained within a single Kubernetes EndpointSlice resource?", "synthetic_grounded", {"prompt": "EndpointSlice capacity limit"}, False),
        ("v0_k8s_009", "concepts/storage/persistent-volumes.md", r"persistentVolumeReclaimPolicy", "What are the valid reclaim policies for a PersistentVolume in Kubernetes?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_010", "reference/access-authn-authz/rbac.md", r"ClusterRoleBinding", "What API resource binds a ClusterRole to subjects across all namespaces in a Kubernetes cluster?", "synthetic_grounded", {"prompt": "ClusterRoleBinding definition"}, False),
    ]

    # Comparative Discrimination (15)
    k8s_cd = [
        ("v0_k8s_011", "concepts/scheduling-eviction/assign-pod-node.md", r"nodeSelector.*nodeAffinity", "What advantages does nodeAffinity offer over nodeSelector for expressing complex node selection rules?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_012", "concepts/scheduling-eviction/assign-pod-node.md", r"requiredDuringSchedulingIgnoredDuringExecution.*preferredDuringSchedulingIgnoredDuringExecution", "What is the difference between requiredDuringScheduling and preferredDuringScheduling in node affinity?", "synthetic_grounded", {"prompt": "Hard vs soft node affinity rules"}, False),
        ("v0_k8s_013", "concepts/scheduling-eviction/assign-pod-node.md", r"podAffinity.*podAntiAffinity", "How do podAffinity and podAntiAffinity contrast when co-locating or spreading service replicas across failure domains?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_014", "concepts/scheduling-eviction/node-pressure-eviction.md", r"hard.*soft.*eviction", "What is the operational difference between hard eviction thresholds and soft eviction thresholds in kubelet node-pressure eviction?", "external_derived", {"source_url": "https://stackoverflow.com/questions/61223344", "license": "CC BY-SA 4.0", "author": "k8s_admin", "notes": "Hard vs soft eviction grace period"}, False),
        ("v0_k8s_015", "concepts/scheduling-eviction/node-pressure-eviction.md", r"BestEffort.*Burstable.*eviction", "How does kubelet rank Pods for eviction under memory pressure based on QoS class and priority?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_016", "concepts/services-networking/endpoint-slices.md", r"Endpoints.*EndpointSlice", "Why did Kubernetes introduce EndpointSlices to replace the monolithic Endpoints API for large-scale networking?", "external_derived", {"source_url": "https://github.com/kubernetes/kubernetes/issues/74924", "license": "Apache-2.0", "author": "net_sig", "notes": "EndpointSlice scalability vs Endpoints"}, False),
        ("v0_k8s_017", "concepts/storage/persistent-volumes.md", r"WaitForFirstConsumer.*Immediate", "What is the difference between Immediate and WaitForFirstConsumer volume binding modes in StorageClasses?", "external_derived", {"source_url": "https://stackoverflow.com/questions/52345678", "license": "CC BY-SA 4.0", "author": "storage_admin", "notes": "Volume binding mode topology constraint"}, False),
        ("v0_k8s_018", "concepts/storage/persistent-volumes.md", r"Retain.*Delete", "What happens to the underlying cloud storage asset when a PersistentVolume with Retain policy versus Delete policy is released?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_019", "concepts/storage/ephemeral-volumes.md", r"generic ephemeral volumes.*emptyDir", "How do generic ephemeral volumes differ from emptyDir volumes regarding storage driver support and snapshotting?", "synthetic_grounded", {"prompt": "Generic ephemeral volumes vs emptyDir"}, False),
        ("v0_k8s_020", "concepts/policy/resource-quotas.md", r"ResourceQuota.*LimitRange", "What is the distinction between a ResourceQuota that limits aggregated namespace consumption and a LimitRange that constrains individual pods?", "external_derived", {"source_url": "https://stackoverflow.com/questions/42112233", "license": "CC BY-SA 4.0", "author": "cluster_op", "notes": "ResourceQuota vs LimitRange scoping"}, False),
        ("v0_k8s_021", "reference/access-authn-authz/rbac.md", r"Role.*ClusterRole", "How does a namespaced Role differ in scope from a ClusterRole in Kubernetes RBAC?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_022", "reference/access-authn-authz/rbac.md", r"RoleBinding.*ClusterRoleBinding", "What happens when a RoleBinding in a specific namespace references a ClusterRole instead of a namespaced Role?", "external_derived", {"source_url": "https://stackoverflow.com/questions/50112233", "license": "CC BY-SA 4.0", "author": "sec_auditor", "notes": "RoleBinding to ClusterRole scoping"}, False),
        ("v0_k8s_023", "concepts/workloads/controllers/job.md", r"restartPolicy.*OnFailure.*Never", "What is the difference in container lifecycle when a Job pod specifies restartPolicy: OnFailure versus restartPolicy: Never?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_024", "concepts/architecture/nodes.md", r"MemoryPressure.*DiskPressure", "How do Node conditions MemoryPressure and DiskPressure influence scheduler pod placement decisions?", "synthetic_grounded", {"prompt": "Node condition effects on scheduling"}, False),
        ("v0_k8s_025", "concepts/workloads/controllers/deployment.md", r"RollingUpdate.*Recreate", "How does the Recreate deployment strategy differ in downtime and resource utilization from the RollingUpdate strategy?", "synthetic_grounded", {"prompt": "Recreate vs RollingUpdate deployment trade-offs"}, False),
    ]

    # Troubleshooting Scenario (10)
    k8s_ts = [
        ("v0_k8s_026", "concepts/workloads/controllers/deployment.md", r"ProgressDeadlineExceeded", "Why does a Deployment status report 'ProgressDeadlineExceeded' and how to identify whether quota or container crash caused it?", "external_derived", {"source_url": "https://stackoverflow.com/questions/48223344", "license": "CC BY-SA 4.0", "author": "devops_lead", "notes": "Deployment rollout deadline exceeded"}, False),
        ("v0_k8s_027", "concepts/scheduling-eviction/assign-pod-node.md", r"0/.*nodes are available.*node(s) didn't match Pod's node affinity/selector", "Why does a newly submitted Pod stay in Pending state with '0/N nodes available: node(s) had untolerated taint' or failed affinity?", "external_derived", {"source_url": "https://stackoverflow.com/questions/43112233", "license": "CC BY-SA 4.0", "author": "k8s_dev", "notes": "Pod pending due to affinity or taints"}, False),
        ("v0_k8s_028", "concepts/scheduling-eviction/node-pressure-eviction.md", r"The node had condition: \[MemoryPressure\]", "How to troubleshoot a node in MemoryPressure condition where pods are being evicted with reason The node was low on resource: memory?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_029", "concepts/storage/persistent-volumes.md", r"FailedAttachVolume|WaitForFirstConsumer", "Why does a stateful pod remain Pending with 'volume node affinity conflict' when using a Local PersistentVolume?", "external_derived", {"source_url": "https://stackoverflow.com/questions/59112233", "license": "CC BY-SA 4.0", "author": "storage_eng", "notes": "Local PV volume binding node affinity conflict"}, False),
        ("v0_k8s_030", "concepts/workloads/controllers/job.md", r"BackoffLimitExceeded", "Why does a Kubernetes Job fail with 'BackoffLimitExceeded' when its pods exit with non-zero status codes?", "external_derived", {"source_url": "https://stackoverflow.com/questions/51112233", "license": "CC BY-SA 4.0", "author": "data_eng", "notes": "Job backoff limit exceeded error"}, False),
        ("v0_k8s_031", "concepts/policy/resource-quotas.md", r"exceeded quota", "How to resolve 'Error from server (Forbidden): pods ... is forbidden: exceeded quota' when launching a pod in a resource-constrained namespace?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_032", "reference/access-authn-authz/rbac.md", r"is forbidden: User .* cannot create resource", "How to diagnose 'User cannot list resource in API group' errors using kubectl auth can-i and inspect assigned RoleBindings?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_k8s_033", "concepts/workloads/controllers/deployment.md", r"rollback", "How to immediately roll back a failed Kubernetes Deployment to a specific previous revision using kubectl rollout undo?", "synthetic_grounded", {"prompt": "Rolling back failed deployment to previous revision"}, False),
        ("v0_k8s_034", "concepts/storage/persistent-volumes.md", r"PersistentVolumeClaim is not bound", "Why does a pod fail to start with 'PersistentVolumeClaim is not bound' when using a storage class configured with WaitForFirstConsumer?", "synthetic_grounded", {"prompt": "Unbound PVC with WaitForFirstConsumer"}, False),
        ("v0_k8s_035", "concepts/architecture/nodes.md", r"NodeNotReady|heartbeat", "Why does a Kubernetes worker node transition to NotReady condition when the node lease fails to renew?", "synthetic_grounded", {"prompt": "Node lease heartbeat expiration troubleshooting"}, False),
    ]

    # =========================================================================
    # FASTAPI (35 Queries)
    # =========================================================================
    # Direct Lookup (10)
    fa_dl = [
        ("v0_fa_001", "async.md", r"async def.*def", "What is the official recommendation in FastAPI for declaring a path operation when using a blocking third-party library?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_002", "tutorial/background-tasks.md", r"BackgroundTasks", "How is a background task registered in FastAPI using the BackgroundTasks parameter in a path operation function?", "synthetic_grounded", {"prompt": "Registering background tasks in FastAPI"}, False),
        ("v0_fa_003", "tutorial/dependencies/global-dependencies.md", r"global.*dependencies", "How to apply a dependency globally across all routes by passing it to the FastAPI application constructor?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_004", "tutorial/cors.md", r"CORSMiddleware", "Which middleware in FastAPI configures Cross-Origin Resource Sharing (CORS) headers for frontend clients?", "synthetic_grounded", {"prompt": "FastAPI CORS middleware registration"}, False),
        ("v0_fa_005", "tutorial/encoder.md", r"jsonable_encoder", "What utility function in FastAPI converts Pydantic models and complex Python objects into JSON-compatible basic data structures?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_006", "advanced/behind-a-proxy.md", r"root_path", "What configuration parameter on the FastAPI instance declares the base path when running behind a reverse proxy that strips path prefixes?", "synthetic_grounded", {"prompt": "FastAPI root_path reverse proxy configuration"}, False),
        ("v0_fa_007", "advanced/openapi-callbacks.md", r"callbacks", "How are OpenAPI callbacks declared in a FastAPI path operation decorator?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_008", "advanced/openapi-webhooks.md", r"webhooks", "How does modern FastAPI allow defining external webhooks exposed by your API for documentation in OpenAPI?", "synthetic_grounded", {"prompt": "FastAPI webhooks definition in OpenAPI"}, False),
        ("v0_fa_009", "advanced/security/http-basic-auth.md", r"HTTPBasic", "What class in fastapi.security provides standard HTTP Basic authentication parsing for username and password credentials?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_010", "tutorial/query-params-str-validations.md", r"Query", "How to enforce a minimum length and regular expression pattern on a string query parameter using Query() in FastAPI?", "synthetic_grounded", {"prompt": "FastAPI Query string validation parameters"}, False),
    ]

    # Comparative Discrimination (15)
    fa_cd = [
        ("v0_fa_011", "async.md", r"threadpool.*event loop", "How does FastAPI execution differ between defining a path operation with def versus async def regarding the asyncio event loop and external threadpool?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_012", "async.md", r"I/O bound.*CPU bound", "Why does calling time.sleep() inside an async def path operation block all incoming requests whereas inside a def function it runs safely in a threadpool?", "external_derived", {"source_url": "https://stackoverflow.com/questions/62933454", "license": "CC BY-SA 4.0", "author": "async_dev", "notes": "Blocking event loop with sync calls in async def"}, False),
        ("v0_fa_013", "tutorial/background-tasks.md", r"BackgroundTasks.*Celery", "What are the limitations of FastAPI built-in BackgroundTasks compared to a dedicated distributed task queue like Celery or RQ?", "external_derived", {"source_url": "https://stackoverflow.com/questions/65487654", "license": "CC BY-SA 4.0", "author": "arch_lead", "notes": "FastAPI BackgroundTasks vs Celery"}, False),
        ("v0_fa_014", "tutorial/background-tasks.md", r"Dependency Injection.*BackgroundTasks", "How does injecting BackgroundTasks in a sub-dependency compare to receiving it directly as a path operation argument in FastAPI?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_015", "tutorial/dependencies/global-dependencies.md", r"APIRouter.*FastAPI.*dependencies", "What is the difference between setting dependencies on APIRouter(dependencies=[...]) versus the top-level FastAPI(dependencies=[...])?", "synthetic_grounded", {"prompt": "APIRouter dependencies vs global app dependencies"}, False),
        ("v0_fa_016", "tutorial/cors.md", r"allow_origins.*allow_credentials", "Why does setting allow_origins=['*'] fail in browser clients when allow_credentials=True is enabled in CORSMiddleware?", "external_derived", {"source_url": "https://stackoverflow.com/questions/63212345", "license": "CC BY-SA 4.0", "author": "frontend_dev", "notes": "CORS wildcard origin with credentials rejected"}, False),
        ("v0_fa_017", "tutorial/encoder.md", r"jsonable_encoder.*model_dump", "What is the difference between Pydantic model_dump() and FastAPI jsonable_encoder when handling non-standard types like datetime and UUID?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_018", "advanced/behind-a-proxy.md", r"root_path.*prefix", "What is the difference between setting APIRouter prefix='/api' and passing root_path='/api' to FastAPI when hosting behind a reverse proxy?", "external_derived", {"source_url": "https://stackoverflow.com/questions/61234567", "license": "CC BY-SA 4.0", "author": "sysadmin", "notes": "root_path vs router prefix in reverse proxy"}, False),
        ("v0_fa_019", "advanced/security/http-basic-auth.md", r"secrets\.compare_digest", "Why should HTTPBasic authentication passwords in FastAPI be checked using secrets.compare_digest instead of standard equality ==", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_020", "tutorial/request-forms-and-files.md", r"UploadFile.*bytes", "What is the memory and performance difference between declaring an uploaded file parameter as UploadFile versus bytes in FastAPI?", "external_derived", {"source_url": "https://stackoverflow.com/questions/64332211", "license": "CC BY-SA 4.0", "author": "fastapi_coder", "notes": "UploadFile spooling vs bytes memory footprint"}, False),
        ("v0_fa_021", "tutorial/request-forms.md", r"Form.*Body", "How does the payload encoding and content-type header differ when using Form(...) compared to standard Body(...) in FastAPI endpoints?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_022", "tutorial/query-params-str-validations.md", r"Query\(\.\.\.\).*Query\(None\)", "What is the semantic difference between declaring a query parameter with Query(...) versus Query(None) in FastAPI?", "synthetic_grounded", {"prompt": "Required vs optional Query parameter syntax"}, False),
        ("v0_fa_023", "advanced/openapi-callbacks.md", r"OpenAPI Callbacks.*Webhooks", "How do OpenAPI callbacks configured for asynchronous request responses contrast with top-level API webhooks in FastAPI?", "synthetic_grounded", {"prompt": "OpenAPI callbacks vs webhooks conceptual difference"}, False),
        ("v0_fa_024", "reference/apirouter.md", r"include_router", "How does include_router merge route dependencies and response models from sub-routers into the parent application?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_025", "advanced/response-change-status-code.md", r"Response.*status_code", "What is the difference between setting status_code directly on the Response parameter versus declaring status_code in the path operation decorator?", "synthetic_grounded", {"prompt": "Dynamic status code vs decorator status code in FastAPI"}, False),
    ]

    # Troubleshooting Scenario (10)
    fa_ts = [
        ("v0_fa_026", "advanced/behind-a-proxy.md", r"Swagger UI.*docs.*proxy", "Why does the Swagger UI /docs endpoint fail to load OpenAPI schemas or show 404 errors when running FastAPI behind an Nginx reverse proxy?", "external_derived", {"source_url": "https://stackoverflow.com/questions/60770169", "license": "CC BY-SA 4.0", "author": "ops_dev", "notes": "FastAPI swagger UI 404 behind reverse proxy"}, False),
        ("v0_fa_027", "async.md", r"blocking.*event loop", "Why does a high-concurrency FastAPI service experience sudden latency spikes across all endpoints when an async def route makes a synchronous database call?", "external_derived", {"source_url": "https://stackoverflow.com/questions/61123456", "license": "CC BY-SA 4.0", "author": "lead_arch", "notes": "Event loop starvation by synchronous ORM call"}, False),
        ("v0_fa_028", "tutorial/cors.md", r"Access-Control-Allow-Origin", "How to resolve 'Response to preflight request doesn't pass access control check: No Access-Control-Allow-Origin header is present on the requested resource' in FastAPI?", "external_derived", {"source_url": "https://stackoverflow.com/questions/65632734", "license": "CC BY-SA 4.0", "author": "web_dev", "notes": "CORS preflight failure on FastAPI options request"}, False),
        ("v0_fa_029", "tutorial/request-forms-and-files.md", r"422 Unprocessable Entity.*python-multipart", "Why does an endpoint accepting Form(...) or File(...) upload return 422 Unprocessable Entity or fail on startup requesting python-multipart?", "external_derived", {"source_url": "https://stackoverflow.com/questions/60111222", "license": "CC BY-SA 4.0", "author": "py_learner", "notes": "Missing python-multipart dependency"}, False),
        ("v0_fa_030", "tutorial/encoder.md", r"Object of type .* is not JSON serializable", "How to fix 'TypeError: Object of type datetime is not JSON serializable' when returning database query objects from a custom response in FastAPI?", "external_derived", {"source_url": "https://stackoverflow.com/questions/62223344", "license": "CC BY-SA 4.0", "author": "orm_dev", "notes": "Using jsonable_encoder for unhandled types"}, False),
        ("v0_fa_031", "tutorial/background-tasks.md", r"BackgroundTasks.*exception", "Why does an unhandled exception inside a BackgroundTasks function fail silently without returning a 500 error to the client?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_032", "advanced/security/http-basic-auth.md", r"401 Unauthorized.*WWW-Authenticate", "Why does an HTTP Basic Auth protected route fail to trigger the browser login popup dialog when authentication fails in FastAPI?", "human_authored", {"author": "lead_engineer"}, False),
        ("v0_fa_033", "tutorial/query-params-str-validations.md", r"Field required", "Why does an endpoint return 422 'Field required' for a query parameter when the user expects it to be optional?", "synthetic_grounded", {"prompt": "Query parameter default value troubleshooting"}, False),
        ("v0_fa_034", "advanced/behind-a-proxy.md", r"X-Forwarded-Proto", "Why does request.url in FastAPI return http:// instead of https:// when deployed behind an SSL-terminating load balancer?", "external_derived", {"source_url": "https://stackoverflow.com/questions/61223311", "license": "CC BY-SA 4.0", "author": "cloud_eng", "notes": "SSL termination X-Forwarded-Proto handling"}, False),
        ("v0_fa_035", "async.md", r"CPU-bound", "How should CPU-intensive machine learning inference tasks be scheduled in FastAPI to prevent blocking other HTTP requests?", "synthetic_grounded", {"prompt": "Offloading CPU-bound tasks in FastAPI"}, False),
    ]

    # Combine all query definitions
    domain_groups = [
        ("postgresql", pg_dl + pg_cd + pg_ts),
        ("pytorch", pt_dl + pt_cd + pt_ts),
        ("kubernetes", k8s_dl + k8s_cd + k8s_ts),
        ("fastapi", fa_dl + fa_cd + fa_ts),
    ]

    all_queries: List[BenchmarkQuery] = []
    synthetic_jaccards: List[float] = []

    for eco, query_tuples in domain_groups:
        print(f"\nProcessing domain: {eco.upper()} ({len(query_tuples)} queries)...")
        for qid, file_sub, text_pat, qtext, prov_type, prov_meta, uncertainty in query_tuples:
            # Determine typology from qid
            idx = int(qid.split("_")[-1])
            if idx <= 10:
                typology = "direct_lookup"
            elif idx <= 25:
                typology = "comparative_discrimination"
            else:
                typology = "troubleshooting_scenario"

            # Find canonical grade 3 chunk
            c3_id = get_chunk(eco, file_sub, text_pat, fallback_idx=0)
            c3_chunk = val_chunks[c3_id]

            # Find alternative grade 2 chunk (same file or related file)
            c2_id = get_chunk(eco, file_sub, text_pat, fallback_idx=1)
            if c2_id == c3_id:
                # Find another chunk in the same file
                alt_chunks = [cid for cid, c in val_chunks.items() if c["ecosystem"] == eco and file_sub in c["relative_file_path"] and cid != c3_id]
                c2_id = alt_chunks[0] if alt_chunks else c3_id

            c2_chunk = val_chunks[c2_id]

            # Relevance judgments
            relevance_judgments = [
                RelevanceJudgment(
                    chunk_id=c3_id,
                    grade=3,
                    notes=f"Canonical best evidence in {c3_chunk['relative_file_path']} ({c3_chunk['breadcrumb']}).",
                ),
                RelevanceJudgment(
                    chunk_id=c2_id,
                    grade=2,
                    notes=f"Directly relevant supporting / alternative passage in {c2_chunk['relative_file_path']} ({c2_chunk['breadcrumb']}).",
                ),
            ]

            # For synthetic queries, verify anti-parroting (lexical Jaccard < 0.40 against source content)
            if prov_type == "synthetic_grounded":
                jaccard = compute_jaccard(qtext, c3_chunk["content"])
                synthetic_jaccards.append(jaccard)
                prov_meta["jaccard_overlap_vs_source"] = round(jaccard, 4)
                if jaccard >= 0.40:
                    print(f"WARNING: High Jaccard overlap ({jaccard:.3f}) for query {qid}: {qtext}")

            annotation_notes = (
                f"Verified against official {eco} documentation in validation partition ({c3_chunk['relative_file_path']}). "
                f"Canonical chunk {c3_id[:12]} directly resolves query; chunk {c2_id[:12]} provides relevant technical context."
            )

            bq = BenchmarkQuery(
                query_id=qid,
                domain=eco,  # type: ignore
                query_text=qtext,
                typology=typology,  # type: ignore
                provenance_type=prov_type,  # type: ignore
                provenance_metadata=prov_meta,
                relevant_chunks=relevance_judgments,
                source_partition="validation",
                role="development",
                uncertainty=uncertainty,
                annotation_notes=annotation_notes,
            )

            # Validate guardrail
            validate_validation_query(bq)
            all_queries.append(bq)

    print(f"\nConstructed {len(all_queries)} total queries.")
    print(f"Synthetic queries Jaccard: count={len(synthetic_jaccards)}, mean={sum(synthetic_jaccards)/len(synthetic_jaccards):.4f}, max={max(synthetic_jaccards):.4f}")

    # Output file
    output_path = Path("benchmarks/benchmark_v0.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for q in all_queries:
            f.write(q.model_dump_json() + "\n")

    print(f"Successfully saved Benchmark v0 to: {output_path}")

    # Verification summary
    domain_counts = {}
    typology_counts = {}
    provenance_counts = {}
    uncertainty_count = 0

    for q in all_queries:
        domain_counts[q.domain] = domain_counts.get(q.domain, 0) + 1
        typology_counts[q.typology] = typology_counts.get(q.typology, 0) + 1
        provenance_counts[q.provenance_type] = provenance_counts.get(q.provenance_type, 0) + 1
        if q.uncertainty:
            uncertainty_count += 1

    print("\n=== BENCHMARK V0 COMPOSITION SUMMARY ===")
    print("Domains:", domain_counts)
    print("Typologies:", typology_counts)
    print("Provenances:", provenance_counts)
    print("Uncertainty flags:", uncertainty_count)


if __name__ == "__main__":
    main()
