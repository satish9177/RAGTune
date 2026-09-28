# RAGTune Experiment E7 Readiness Specification

**Document Path**: `benchmarks/canonical/E7_READINESS.md`  
**Date**: 2026-09-28  
**Readiness Status**: **`E7_TRAINING_BLOCKED_PENDING_NEGATIVE_REPAIR_AND_QUERY_POSITIVE_AUDIT`**  
**Target Architecture**: Stage-2 Domain Cross-Encoder Reranker (`BAAI/bge-reranker-base` fine-tuned)  
**Upstream Stage-1 Generator**: `E5C` (SQLite FTS5 BM25 + E4C Matched-Easy Dense via RRF $k=60$)  
**Target Hardware**: NVIDIA GeForce RTX 5050 Laptop GPU (8,151 MiB VRAM, CUDA 12.8, PyTorch 2.11.0+cu128)

---

## 1. Partition Counts & Strict Mining Boundary

All training pairs for E7 must originate strictly from the canonical frozen `train` partition. No queries, passages, or candidates from `validation` or `frozen_test` may enter training.

### Exact Partition Counts (Verified against `benchmarks/partition_manifest.json`)

| Partition | Permitted for E7 Training? | File Count | Exact Chunk Count | Percentage of Corpus |
| :--- | :---: | :---: | :---: | :---: |
| **`train`** | **YES (STRICTLY EXCLUSIVE)** | **743 files** | **6,414 chunks** | **55.08%** |
| **`validation`** | **NO (FROZEN EVALUATION ONLY)** | 184 files | 1,575 chunks | 13.53% |
| **`frozen_test`** | **NO (STRICT ISOLATION)** | 313 files | 3,656 chunks | 31.39% |
| **Total Corpus** | — | **1,240 files** | **11,645 chunks** | **100.00%** |

- **Assertion**: $\text{train} (6,414) + \text{validation} (1,575) + \text{frozen\_test} (3,656) = 11,645$.
- **Automated Guardrail**: Any script attempting to mine or load chunk IDs outside the 6,414 canonical train chunk IDs will raise an immediate exception.

---

## 2. Permitted Training Queries

Training pairs use strictly the canonical train-split queries generated during Phase 3 and locked in:
- **Primary Manifest**: `data/training/E7_PRIMARY_QUERY_MANIFEST.json` (SHA-256: `a0cb391c36c1f1d54d8712d9bfe540e4792f0ae8eb6826e68d6bda02d14dffd5`)
- **Total Permitted Query Count**: Exactly **188 queries**
- **Query ID Distribution**: PyTorch: 59, PostgreSQL: 45, Kubernetes: 43, FastAPI: 41 (all prefixed with `train_`)
- **Query Source Partition**: 100% `train` (`query_source_partition: "train"`)
- **Positive Chunk Partition**: 100% `train` (`positive_source_partition: "train"`)
- **Structural Quality Report**: `data/training/E7_QUERY_POSITIVE_QUALITY.json` (125 `CLEAN`, 59 `REVIEW_QUERY`, 4 `REVIEW_POSITIVE_MAPPING`)

---

## 3. Candidate Depth: Top-20 Locked

E7 will operate on **Top-20 candidates** retrieved by Stage-1 `E5C`:
- **Stage-1 Coverage**:
  - $\text{HitRate@10} = 137 / 140$ ($97.86\%$)
  - **$\text{HitRate@20} = 139 / 140$ ($99.29\%$)**
  - $\text{HitRate@50} = 139 / 140$ ($99.29\%$)
- **Sole Candidate Miss**: `v0_k8s_032` is the only unretrieved query at Top-20 (and remains absent at Top-50).
- **Depth Justification**: Expanding from Top-20 to Top-50 provides **zero** additional hit availability ($+0.0000$ HitRate), while multiplying cross-encoder inference latency by $2.5\times$ ($+771.4$ ms) and introducing 30 distractor candidates per query.

---

## 4. Generic E6 Failure Rationale

The un-fine-tuned cross-encoder `BAAI/bge-reranker-base` was profiled in E6 and rejected:
1. **Ranking Degradation**:
   - On Top-20: $\Delta \text{NDCG@10} = -0.0088$, $\Delta \text{Recall@10} = -0.0357$ (statistically significant degradation, 95% BCa CI `[-0.0714, -0.0036]`), and top-10 failures tripled from 3 to 9.
   - On Top-50: $\Delta \text{NDCG@10} = -0.0268$, $\Delta \text{Recall@10} = -0.0679$, and top-10 failures quadrupled to 12.
2. **In-Pool Demotions**: Demoted **11 answer-bearing passages** that were already present in Stage-1 Top-10 completely outside the Top-10.
3. **Domain Gap**: Pretrained MS-MARCO web weights favor generic expository text and broad documentation over concise configuration flags (e.g. `wal_level`, `maintenance_work_mem`), API decorators, and error message syntax.
4. **Latency Budget Violation**: Added 421.6 ms (Top-20) to 1,193.0 ms (Top-50) per query.

---

## 5. Hardware Budget & Training Profiling (RTX 5050 8GB)

- **Total GPU Memory**: 8,151 MiB VRAM
- **Architecture**: `BAAI/bge-reranker-base` (~110M parameters)
- **Precision**: PyTorch FP16 / AMP (`torch.cuda.amp.autocast`)
- **Max Sequence Length**: 384 tokens
- **Per-Device Batch Size**: 16 pairs (effective batch size 64 via 4 gradient accumulation steps)
- **Estimated VRAM Consumption**:
  - Model weights: ~220 MiB
  - Optimizer states (AdamW): ~440 MiB
  - Activations & gradients (batch 16, len 384): ~3,100 MiB
  - Total training footprint: **~3.8 GiB to 4.2 GiB** (~47% to 52% of total VRAM)
- **Headroom**: >3.9 GiB free VRAM buffer, guaranteeing zero CUDA Out-of-Memory (OOM) risk.

---

## 6. Audit Diagnostic Findings & Multi-Signal Semantic Shields

### A. Failure of Circular Teacher Certification (`E7_NEGATIVE_AUDIT_40`)
An AI diagnostic review of the initial E7 audit revealed that **relying solely on `BAAI/bge-reranker-base` teacher score thresholds is invalid** because the generic teacher suffers from domain-ranking errors:
- **Audit Result**: TRUE_NEGATIVE: 20/40 (50.0%), **FALSE_NEGATIVE: 13/40 (32.5%)**, AMBIGUOUS: 7/40 (17.5%).
- **Preserved Artifacts**:
  - Historical Audit: [`data/training/E7_NEGATIVE_AUDIT_40.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40.md) & [`E7_NEGATIVE_AUDIT_40.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40.json)
  - Failure Diagnostic Report: [`data/training/E7_NEGATIVE_AUDIT_40_AI_REVIEW.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40_AI_REVIEW.md) (Status: `AI_REVIEW_FAILED_NEGATIVE_QUALITY_GATE`)

### B. Multi-Signal Semantic Shields Implemented
To replace circular teacher certification, multi-signal semantic shields were constructed and enforced:
1. **Strict Same-Document Quarantine**: All candidates from the same document file as the positive are unconditionally quarantined (`SAME_DOCUMENT_CONTEXT_LEAK`), preventing adjacent section leakages.
2. **Comparative Query Partial / Both-Side Answer Shield**: If a query compares entities A and B, any candidate substantively explaining A, B, or both is quarantined. Partial answers cannot be trained as negatives.
3. **Exact Technical Entity + Action/Configuration Language**: Candidates containing exact query entities alongside configuration, YAML, procedure, or function behavior syntax are quarantined.
4. **Troubleshooting Resolution / Diagnostics Shield**: Candidates containing error handling, recovery, or diagnostic steps for queried error states are quarantined.
5. **Non-Circular Teacher Safeguards**: Margin $\ge 0.25$, $0.02 \le s_{\text{neg}} < 0.60$, $s_{\text{pos}} \ge 0.30$.
6. **Hardness Criteria**: Rejects trivial distractors ($s_{\text{neg}} < 0.02$ or rank $> 10$ with low score or navigation tables).

### C. Reclassification Transitions (Historical 1,216 SAFE_V1 Pool)
Rerunning the shields against the historical 1,216 candidates produced:
- **`SAFE_V1 -> SAFE_NEGATIVE_V2`**: **652** (53.62%)
- **`SAFE_V1 -> QUARANTINE_POSSIBLE_FALSE_NEGATIVE`**: **522** (42.93%)
- **`SAFE_V1 -> REJECT_KNOWN_RELEVANT`**: **0** (0.00%)
- **`SAFE_V1 -> REJECT_TOO_EASY`**: **42** (3.45%)

Across all 3,760 candidates in the V2 ledger:
- `SAFE_NEGATIVE_V2`: 652 (17.34%) — PyTorch: 166, FastAPI: 200, Kubernetes: 149, PostgreSQL: 137
- `QUARANTINE_POSSIBLE_FALSE_NEGATIVE`: 1,821 (48.43%)
- `REJECT_KNOWN_RELEVANT`: 186 (4.95%)
- `REJECT_TOO_EASY`: 1,101 (29.28%)
- Unique queries with safe negatives: **139 / 188** (49 queries have zero safe negatives; median: 3.0, max: 16).
- Persisted in [`data/training/e7_candidate_ledger_v2.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_candidate_ledger_v2.jsonl), [`data/training/e7_safe_negatives_v2.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_safe_negatives_v2.jsonl), and [`data/training/e7_candidate_disposition_v2.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_candidate_disposition_v2.json).

---

## 7. Human Verification Audits (Prerequisites for Training)

### A. Focused Query-Positive Audit (11 Queries)
- **Artifacts**: [`data/training/E7_QUERY_POSITIVE_AUDIT.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_QUERY_POSITIVE_AUDIT.md) & [`E7_QUERY_POSITIVE_AUDIT.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_QUERY_POSITIVE_AUDIT.json)
- **Selection**: Deduplicated union of `REVIEW_POSITIVE_MAPPING` (4), `HEADING_ARTIFACT` (7), and `VERY_LOW_LEXICAL_OVERLAP` (2).
- **Status**: `PENDING_HUMAN_AUDIT` (human fields blank).

### B. Regenerated E7 Negative Verification Audit V2 (40 Items)
- **Artifacts**: [`data/training/E7_NEGATIVE_AUDIT_40_V2.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40_V2.md) & [`E7_NEGATIVE_AUDIT_40_V2.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40_V2.json)
- **Stratification**: 10 PostgreSQL, 10 PyTorch, 10 Kubernetes, 10 FastAPI; Direct Lookup (20), Comparative (15), Troubleshooting (5).
- **Predeclared Acceptance Gate**:
  - **ZERO confirmed FALSE_NEGATIVE**
  - **At most 2 AMBIGUOUS among 40** (ambiguous rows excluded from training)
  - **All confirmed TRUE_NEGATIVE rows judged at least MODERATE_CONFUSER**
- **Status**: `PENDING_HUMAN_AUDIT` (human fields blank).

---

## 8. Summary Checklist & Explicit Training Prerequisites

```
================================================================================
E7 EXPERIMENT READINESS CHECKLIST
================================================================================
[x] Canonical TRAIN chunk count verified:            6,414 chunks (exact)
[x] Permitted TRAIN query set locked:                188 queries (manifest verified)
[x] Stage-1 upstream candidate pool locked:          E5C Top-20 (HitRate = 99.29%)
[x] E6 generic reranker failure diagnosis:           Documented (11 demotions)
[x] GPU memory budget profiled (RTX 5050 8GB):       ~3.8 GiB footprint (PASS)
[x] SciFact OOD benchmark status:                    OOD_DEV_CONSUMED
[x] Final OOD benchmarks (FiQA / BRIGHT):            RESERVED & UNTOUCHED
[x] Failed V1 audit diagnostic review recorded:      AI_REVIEW_FAILED_NEGATIVE_QUALITY_GATE
[x] Multi-signal semantic shields implemented:       Strict same-doc, entity, comparative
[x] V2 candidate pool reclassified:                  652 SAFE_NEGATIVE_V2 candidates
[ ] Prerequisite 1: E7_QUERY_POSITIVE_AUDIT:         PENDING_SATISH_HUMAN_REVIEW
[ ] Prerequisite 2: E7_NEGATIVE_AUDIT_40_V2:         PENDING_SATISH_HUMAN_REVIEW (Gate)
[ ] Prerequisite 3: Final capped candidate dataset:   Cap max 3 neg/query after signoff
================================================================================
FINAL READINESS STATE: E7_TRAINING_BLOCKED_PENDING_NEGATIVE_REPAIR_AND_QUERY_POSITIVE_AUDIT
================================================================================
```

