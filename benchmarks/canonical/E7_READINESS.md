# RAGTune Experiment E7 Readiness Specification

**Document Path**: `benchmarks/canonical/E7_READINESS.md`  
**Date**: 2026-09-28  
**Readiness Status**: **`READY_FOR_TRAINING_AFTER_E7_NEGATIVE_HUMAN_AUDIT`**  
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

## 6. Pre-Condition: Hard-Negative Human Audit Status

### A. Historical E4 Audit (`HARD_NEGATIVE_AUDIT_40`)
- Preserved unchanged as historical evidence in [`data/training/HARD_NEGATIVE_AUDIT_40.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/HARD_NEGATIVE_AUDIT_40.md).
- AI diagnostic review recorded in [`data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/HARD_NEGATIVE_AUDIT_40_AI_REVIEW.json):
  - 4 `FALSE_NEGATIVE`, 6 `AMBIGUOUS_UNSAFE_NEGATIVE`, 30 `LIKELY_TRUE_NEGATIVE`.
  - Diagnosed `train_fa_0377` query-positive mapping defect.
- Declared as **AI-assisted recommendations only**; human review status remains `PENDING_SATISH_HUMAN_REVIEW`.

### B. E7 Candidate Mining & Safe Negative Pool
- **Mining Foundation**: `E5C` (BM25 + E4C Dense Hybrid Fusion RRF $k=60$) over all 6,414 `train` chunks.
- **Candidate Ledger**: [`data/training/e7_candidate_ledger.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/data/training/e7_candidate_ledger.jsonl) (3,760 total candidates across 188 queries).
- **Candidate Disposition**:
  - **`SAFE_NEGATIVE`**: 1,216 (32.34%) — PyTorch: 372, FastAPI: 328, Kubernetes: 268, PostgreSQL: 248.
  - **`QUARANTINE_POSSIBLE_FALSE_NEGATIVE`**: 1,044 (27.77%)
  - **`REJECT_KNOWN_RELEVANT`**: 186 (4.95%)
  - **`REJECT_TOO_EASY`**: 1,314 (34.95%)
- **Quarantine Reasons Breakdown**:
  - `SAME_DOCUMENT_SUBTOPIC_PROXIMITY`: 357
  - `HIGH_TEACHER_SCORE_PROBABLE_ANSWER`: 278
  - `AMBIGUOUS_TEACHER_MARGIN`: 184
  - `TEACHER_INVERSION_OR_TIE`: 148
  - `LOW_POSITIVE_TEACHER_CONFIDENCE`: 67
  - `HIGH_LEXICAL_OVERLAP_WITH_POSITIVE`: 10

### C. Dedicated E7 Human Verification Audit Packet
- **Markdown Audit Packet**: [`data/training/E7_NEGATIVE_AUDIT_40.md`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40.md)
- **Machine-Readable Companion**: [`data/training/E7_NEGATIVE_AUDIT_40.json`](file:///c:/Users/SATISH/projects/RAGTune/data/training/E7_NEGATIVE_AUDIT_40.json)
- **Current Status**: **`PENDING_HUMAN_AUDIT`**
- **Non-Negotiable Rule**: No domain reranker training (E7) will begin until Satish personally reviews and approves the 40-triple audit sample. No human approval will be simulated.

---

## 7. OOD Benchmarks Isolation Status

- **Consumed Development Benchmark**:
  - `mteb/scifact test`: Marked **`OOD_DEV_CONSUMED`** (used for development non-degradation checks). Must **NOT** be used as untouched OOD-final evidence.
- **Reserved Untouched Final Benchmarks**:
  - `mteb/fiqa` (financial QA)
  - `BRIGHT` technical and distinct OOD subsets (Su et al., 2024; Biology, Earth Science, Economics)
  - Both datasets remain completely untouched, uninspected, and reserved for final production certification.

---

## 8. Summary Checklist & Readiness State

```
================================================================================
E7 EXPERIMENT READINESS CHECKLIST
================================================================================
[x] Canonical TRAIN chunk count verified:            6,414 chunks (exact)
[x] Permitted TRAIN query set verified:              188 queries (train_* only)
[x] Stage-1 upstream candidate pool locked:          E5C Top-20 (HitRate = 99.29%)
[x] E6 generic reranker failure diagnosis:           Documented (11 demotions)
[x] GPU memory budget profiled (RTX 5050 8GB):       ~3.8 GiB footprint (PASS)
[x] SciFact OOD benchmark status:                    OOD_DEV_CONSUMED
[x] Final OOD benchmarks (FiQA / BRIGHT):            RESERVED & UNTOUCHED
[ ] Hard-negative 40-triple human audit:             PENDING_HUMAN_AUDIT
================================================================================
FINAL READINESS STATE: READY_FOR_TRAINING_AFTER_HUMAN_NEGATIVE_AUDIT
================================================================================
```
