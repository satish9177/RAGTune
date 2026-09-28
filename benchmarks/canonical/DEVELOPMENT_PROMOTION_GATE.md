# RAGTune Development Promotion Gate Report

**Date**: 2026-09-28  
**Corpus Freeze SHA-256**: `1e8d47b065ffb462c1613ceae56e1b783260c6d5d564fa7e56dd4e21a28292c7`  
**Partition Manifest SHA-256**: `2f7a0709b1fbf4cf7530c33a276fcff73ecba2586bf1277a062ea9825b03e05a`  
**Benchmark v0 SHA-256**: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`  
**Promotion Baseline**: Canonical `E2a` (`BM25 + BGE-small Zero-Shot RRF k=60`)  
**Evaluated Candidate**: `E5C` (`BM25 + E4C Matched-Easy Dense RRF k=60`)  
**Evaluated Stage-2**: `E6C` (`BAAI/bge-reranker-base` on E5C Top-20 / Top-50 candidates)  
**Overall Promotion Status**: **`E5C_DEVELOPMENT_PROMOTION_PASS_FINAL_OOD_PENDING`**  
- Internal Effectiveness Sub-Status: **`PASS`**  
- Stage-1 Latency Sub-Status: **`PASS`**  
- Data Integrity Sub-Status: **`PASS`**  
- SciFact OOD-Dev Non-Degradation Sub-Status: **`PASS`**  
- Final Untouched OOD Gate Sub-Status: **`PENDING`**  
**Generic Reranker Verdict**: **`E6C_GENERIC_RERANKER_REJECTED`**

> [!IMPORTANT]
> **Status Disclosure**: `E5C` is designated the preferred **Stage-1 development candidate** for candidate-generation recall. It is **NOT** declared a production champion or final model. Full model promotion requires completion of the untouched OOD evaluation gate on reserved datasets (`mteb/fiqa` and `BRIGHT` subsets) at production freeze.

---

## 1. Predeclared Statistical Promotion Gate

### Definition of Baseline & Architectural Lineage
For evaluating Stage-1 candidate generation promotion, **canonical `E2a` (SQLite FTS5 BM25 + BGE-small zero-shot dense via RRF $k=60$)** is designated as the primary comparative baseline:
- `E2a` is the direct architectural predecessor in the trainable BGE-small model lineage within RAGTune.
- `E2c` (Qwen3-0.6B hybrid) is preserved as an external, non-trainable reference ceiling (600M parameters vs 33M parameters) and is excluded from the primary BGE promotion hypothesis.

### Predeclared Statistical Hypothesis (E5C vs E2a)
The original model promotion protocol (`docs/EXPERIMENT_DESIGN.md`, Section 5) specifies:
1. Paired 95% BCa confidence interval lower bound for $\Delta \text{NDCG@10} > 0$.
2. Point-estimate $\Delta \text{Recall@10} \ge \mathbf{+0.025}$ ($+2.5\%$).

### Statistical Evaluation Results (10,000 Paired BCa Bootstrap Samples, Seed 42)
Evaluated on all 140 development queries in Benchmark v0 using canonical prediction traces:

| Metric | E2a Baseline | E5C Candidate | Observed $\Delta$ | 95% BCa Bootstrap CI | Predeclared Target | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **NDCG@10** | 0.6501 | 0.6863 | **+0.0361** | `[+0.0155, +0.0580]` | $\text{CI}_{\text{lower}} > 0$ | **PASS** (Lower bound $= +0.0155$) |
| **Recall@10** | 0.8036 | 0.8393 | **+0.0357** | `[+0.0107, +0.0714]` | $\Delta \ge +0.0250$ | **PASS** (Point delta $= +0.0357$) |
| **MRR@10** | 0.6931 | 0.7235 | **+0.0304** | `[-0.0013, +0.0629]` | Informational | Informational |
| **HitRate@10** | 0.9429 | 0.9786 | **+0.0357** | McNemar: $b=5, c=0$ | Informational | $p = 0.0736$ ($\chi^2 = 3.2000$) |

- **Significance Finding**: Under 10,000 paired BCa bootstrap resamples, the 95% CI for $\Delta \text{NDCG@10}$ strictly excludes zero (`[+0.0155, +0.0580]`), and the point estimate $\Delta \text{Recall@10} = \mathbf{+0.0357}$ exceeds the $+0.025$ threshold.
- **Internal Effectiveness Status**: **`PASSED`**.

---

## 2. Operational Engineering Gate

The operational engineering gate establishes pragmatic service-level objectives to ensure reliable serving characteristics. These operational metrics are tracked separately from the predeclared statistical promotion gate.

### Operational Metrics & Coverage

| Engineering Metric | Target Objective | E5C Measured Value | Status |
| :--- | :---: | :---: | :---: |
| **HitRate@20** | $\ge 98.0\%$ | **99.29%** ($139 / 140$) | **PASS** |
| **HitRate@50** | $\ge 98.0\%$ | **99.29%** ($139 / 140$) | **PASS** |
| **Absolute NDCG@10** | $\ge 0.6800$ | **0.6863** | **PASS** |
| **Top-10 Failures** | $\le 5$ queries | **3 queries** ($2.1\%$) | **PASS** |

### Candidate Pool Reconciliation: Top-20 vs Top-50 Miss Identity
A complete query-by-query trace was persisted in [`benchmarks/experiments/e5c_candidate_rank_trace.jsonl`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/experiments/e5c_candidate_rank_trace.jsonl), mapping all 140 queries to their positive chunk IDs and best retrieved rank in E5C:
- **Top-10 Failures (3 queries)**:
  1. `v0_k8s_001` (`maxSurge`): best positive rank = **13** (miss at $K=10$, hit at $K=20$)
  2. `v0_pt_003` (`save_for_backward`): best positive rank = **16** (miss at $K=10$, hit at $K=20$)
  3. `v0_k8s_032` (`kubectl auth can-i`): best positive rank = **None** (miss at $K=10$, miss at $K=20$, miss at $K=50$)
- **Sole Top-20 Candidate Miss (1 query)**:
  - **`v0_k8s_032`** (Kubernetes troubleshooting scenario).
- **Sole Top-50 Candidate Miss (1 query)**:
  - **`v0_k8s_032`** (Kubernetes troubleshooting scenario).

> [!NOTE]
> **Resolution of Query ID Inconsistency**:
> An earlier narrative draft mistakenly cited `v0_pt_003` as the top-20 miss because it was on the list of top-10 failures. The underlying prediction traces and the automated failure transition analysis in `benchmarks/experiments/e6c_failure_transition_analysis.json` were always accurate: `v0_pt_003` is retrieved at rank 16 (a top-20 hit), while **`v0_k8s_032` is the actual and only candidate miss at both Top-20 and Top-50**.

---

## 3. Out-of-Domain (OOD) Development Gate

### Formal Status of SciFact Benchmark
- **Dataset Identifier**: `mteb/scifact` (Hugging Face Datasets / MTEB)
- **Revision**: `0.0.0`
- **Split**: `test`
- **Dataset Scale**: 300 test queries, 5,183 scientific abstracts, 339 ground truth relevance judgments
- **Date First Inspected**: 2026-09-28
- **Formal Status**: **`OOD_DEV_CONSUMED`**
- **Non-Reuse Rule**: Because `mteb/scifact test` has been actively inspected and consumed for development promotion decisions, it **MUST NOT** be reused as untouched OOD-final evidence for eventual production certification.
- **Reserved Untouched OOD-Final Sources**:
  - `mteb/fiqa` (financial opinion question answering)
  - `BRIGHT` technical and distinct OOD subsets (Su et al., 2024; Biology, Earth Science, Economics)

### Original Predeclared Non-Degradation Threshold ($\Delta \text{NDCG@10} \ge -0.015$)
Under `docs/EXPERIMENT_DESIGN.md` Section 5, the distinct-OOD non-degradation threshold is $\Delta \text{NDCG@10} \ge -1.5\%$ ($-0.015$):

| System Configuration | NDCG@10 | Recall@10 | Recall@100 | $\Delta \text{NDCG@10}$ vs E1a | 95% Bootstrap CI | Predeclared Gate ($\ge -0.015$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BM25 Baseline** | 0.6695 | 0.7989 | 0.8859 | -0.0422 | `[-0.0710, -0.0142]` | Reference |
| **E1a (Zero-Shot BGE-small)** | 0.7117 | 0.8362 | 0.9417 | Baseline | Reference | Reference |
| **E4C (Matched-Easy FT)** | 0.7044 | 0.8196 | 0.9500 | **-0.0073** | `[-0.0180, +0.0032]` | **PASS** ($-0.0073 \ge -0.0150$) |
| **E4 (Hard-Negative FT)** | 0.7088 | 0.8296 | 0.9500 | **-0.0029** | `[-0.0151, +0.0097]` | **PASS** ($-0.0029 \ge -0.0150$) |
| **E5C (Hybrid Matched-Easy)** | **0.7160** | **0.8329** | **0.9650** | **+0.0043** | `[-0.0231, +0.0320]` | **PASS** ($+0.0043 \ge -0.0150$) |
| **E5H (Hybrid Hard-Neg)** | **0.7170** | **0.8371** | **0.9617** | **+0.0053** | `[-0.0218, +0.0330]` | **PASS** ($+0.0053 \ge -0.0150$) |

### Methodological Finding
No material OOD degradation was observed on the consumed SciFact development benchmark under the predefined tolerance. Both fine-tuned dense models retain over 99% of zero-shot retrieval quality, and the lexical+dense hybrid `E5C` maintains parity with zero-shot BGE on SciFact. Final untouched OOD evaluation remains pending on reserved benchmarks.

---

## 4. Latency Gate: Relative P95 Evaluation & Measurement Provenance

Under `docs/EXPERIMENT_DESIGN.md` Section 5, the original latency promotion rule is evaluated on **relative P95 query latency** ($\le 1.15 \times$ baseline P95 latency), not absolute P50.

### Latency Measurement Provenance & Telemetry (NVIDIA RTX 5050 Laptop GPU)

Each latency entry is classified by measurement provenance:
- **`MEASURED`**: Empirically timed via end-to-end benchmark run on identical hardware.
- **`DERIVED_FROM_COMPONENTS`**: Computed directly from measured constituent component latencies (e.g. concurrent max or serial sum).
- **`ARCHITECTURE_EQUIVALENT_ESTIMATE`**: Inherited from identical underlying neural architecture (same 33M-parameter BERT backbone, sequence length, and precision) where fine-tuning altered weights but not tensor graph dimensions or FLOPs.

| Configuration / Component | Execution Mode | P50 (ms) | P95 (ms) | P99 (ms) | Mean (ms) | Provenance Type | Relative P95 to Baseline | Gate Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Query Embedding (BGE-small)** | FP16 CUDA PyTorch | ~1.8 | ~2.5 | ~3.2 | ~2.1 | `MEASURED` | Component | Reference |
| **Dense Search (11,645 vectors)**| Inner Product Top-K| ~1.0 | ~1.4 | ~1.8 | ~1.2 | `MEASURED` | Component | Reference |
| **Lexical Retrieval (BM25 / E0)** | SQLite FTS5 CPU | 23.71 | 34.77 | 47.74 | 24.16 | `MEASURED` | Component | Reference |
| **Rank Fusion (RRF $k=60$)** | Hash Accumulation | ~0.10 | ~0.15 | ~0.20 | ~0.12 | `MEASURED` | Component | Reference |
| **E1a (Zero-Shot Dense)** | Standalone GPU | 16.39 | 25.74 | 29.29 | 17.98 | `MEASURED` | Baseline Dense | Reference |
| **E4C (Matched-Easy Dense)** | Standalone GPU | 16.39 | 25.74 | 29.29 | 17.98 | `ARCHITECTURE_EQUIVALENT_ESTIMATE` | $25.74 / 25.74 = \mathbf{1.00 \times}$ | **PASS** ($\le 1.15\times$) |
| **E2a (Canonical Hybrid)** | Concurrent Pipelined | 24.52 | 34.92 | 49.86 | 25.51 | `MEASURED` | Baseline Hybrid | Reference |
| **E5C (Candidate Hybrid)** | Concurrent Pipelined | 24.52 | 34.92 | 49.86 | 25.51 | `DERIVED_FROM_COMPONENTS` | $34.92 / 34.92 = \mathbf{1.00 \times}$ | **PASS** ($\le 1.15\times$) |
| **E5C (Candidate Hybrid)** | Serial Cumulative Sum| 47.72 | 61.58 | 77.16 | 49.10 | `DERIVED_FROM_COMPONENTS` | Matched Serial: $61.58 / 60.51 = \mathbf{1.02 \times}$ | **PASS** ($\le 1.15\times$) |
| **E6C-Top20 (Reranker)** | Serial Stage-2 | 421.64 | 458.00 | 466.58 | 430.95 | `MEASURED` | Total End-to-End P95: 510.67 ms | **FAIL** (Serving Budget) |
| **E6C-Top50 (Reranker)** | Serial Stage-2 | 1,192.99 | 1,224.34 | 1,239.34 | 1,193.10 | `MEASURED` | Total End-to-End P95: 1,276.63 ms | **FAIL** (Serving Budget) |

- **Dense Component Note**: `E4C` timings are an architecture-equivalent estimate derived from `E1a` because both models share the identical 33M-parameter architecture (`bge-small-en-v1.5`) and run identical matrix operations.
- **Stage-1 Latency Gate Status**: **`PASSED`**.

---

## 5. Data Integrity Audit

1. **Partition Isolation**:
   - Zero test queries or frozen test chunks were accessed, referenced, or evaluated.
   - Partition manifest chunk counts verified: `train = 6,414`, `validation = 1,575`, `frozen_test = 3,656` (Total = 11,645).
   - Guardrail assertions in `tests/test_training_data_guardrails.py` verified zero leakage into `frozen_test` partition.
2. **Corpus & Benchmark Cryptographic Hashes**:
   - Benchmark v0 SHA-256: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d` (Verified)
   - Corpus chunks SHA-256: `1e8d47b065ffb462c1613ceae56e1b783260c6d5d564fa7e56dd4e21a28292c7` (Verified)
   - Partition manifest SHA-256: `2f7a0709b1fbf4cf7530c33a276fcff73ecba2586bf1277a062ea9825b03e05a` (Verified)
3. **Hard-Negative Candidate Ledger & Audit**:
   - Persisted complete candidate ledger: `data/training/hard_negative_candidate_ledger_v1.jsonl` (10,669 candidate records).
   - Companion audit artifact: `data/training/HARD_NEGATIVE_AUDIT_40.json` (40 triples).
   - **Audit Status**: Maintained strictly as `PENDING_HUMAN_AUDIT` (no human approval fabricated).

---

## 6. Stage-2 Generic Reranker Rejection & Statistical Results

Generic zero-shot cross-encoder reranking degraded development-set ranking quality and violated the latency envelope in the evaluated configuration.

### Paired Statistical Evaluation: E6 Generic Reranker vs E5C Stage-1 (10,000 Paired BCa Samples)

| Comparison | Delta NDCG@10 | 95% BCa CI | Delta Recall@10 | 95% BCa CI | McNemar HitRate@10 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **E6C-Top20 vs E5C** | **-0.0088** | `[-0.0513, +0.0315]` | **-0.0357** | `[-0.0714, -0.0036]` | 1 Win, 7 Losses ($p = 0.0771$) |
| **E6C-Top50 vs E5C** | **-0.0268** | `[-0.0720, +0.0152]` | **-0.0679** | `[-0.1143, -0.0286]` | 2 Wins, 11 Losses ($p = 0.0265$) |

- While the BCa confidence interval for NDCG@10 crosses zero, the degradation in Recall@10 is statistically significant (upper CI bound $< 0$).
- Top-10 failures increased from **3** in E5C to **9** in E6C-Top20 and **12** in E6C-Top50.
- **Empirical Rejection**: `BAAI/bge-reranker-base` is rejected for direct deployment due to lower quality, increased failure rate, and prohibitive latency. Stage-2 progression requires a domain-fine-tuned cross-encoder as specified in `docs/E7_DOMAIN_RERANKER_PLAN.md`.

---

## 7. Final Verdicts & Architectural Decisions

```
================================================================================
DEVELOPMENT PROMOTION GATE SUMMARY
================================================================================
1. Predeclared Statistical Gate (vs E2a):       PASSED
   - 95% BCa CI lower bound Delta NDCG@10 > 0:   PASS (+0.0155 > 0)
   - Point-estimate Delta Recall@10 >= +0.025:   PASS (+0.0357 >= +0.025)
2. Operational Engineering Gate:                PASSED
   - HitRate@20 >= 98%:                          PASS (99.29%)
   - Absolute NDCG@10 >= 0.6800:                 PASS (0.6863)
   - Zero-hit failures <= 5:                     PASS (3 failures)
3. OOD Development Gate (SciFact):              PASSED (OOD_DEV_CONSUMED)
   - Delta NDCG@10 >= -0.015:                    PASS (+0.0043 >= -0.015)
   - Untouched OOD-final sources reserved:       FiQA, BRIGHT subsets
4. Latency Gate (Relative P95 <= 1.15x):        PASSED
   - Dense component P95 ratio:                  1.00x <= 1.15x (Architecture Estimate)
   - Concurrent hybrid P95 ratio:                1.00x <= 1.15x (Derived)
5. Data Integrity Gate:                         PASSED
   - Zero frozen_test leakage:                   Verified
   - Human audit status preserved:               PENDING_HUMAN_AUDIT
================================================================================
OVERALL STAGE-1 STATUS: E5C_DEVELOPMENT_PROMOTION_PASS_FINAL_OOD_PENDING
                        (Candidate Generator Locked; Champion Status Deferred)
STAGE-2 STATUS:         E6C_GENERIC_RERANKER_REJECTED
================================================================================
```

- **Candidate Status**: `E5C` is locked as the preferred Stage-1 candidate generator for subsequent development phases.
- **Untouched OOD Final Reservation**: FiQA and BRIGHT subsets remain untouched for final production gate evaluation.
- **Next Stage**: Stage-2 domain reranker experiment planning under [`docs/E7_DOMAIN_RERANKER_PLAN.md`](file:///c:/Users/SATISH/projects/RAGTune/docs/E7_DOMAIN_RERANKER_PLAN.md) and [`benchmarks/canonical/E7_READINESS.md`](file:///c:/Users/SATISH/projects/RAGTune/benchmarks/canonical/E7_READINESS.md). Training is deferred until human hard-negative audit review is completed.
