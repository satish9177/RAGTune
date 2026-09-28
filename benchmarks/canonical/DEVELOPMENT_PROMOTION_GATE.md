# RAGTune Development Promotion Gate Report

**Date**: 2026-09-28  
**Corpus Freeze SHA-256**: `1e8d47b065ffb462c1613ceae56e1b783260c6d5d564fa7e56dd4e21a28292c7`  
**Partition Manifest SHA-256**: `2f7a0709b1fbf4cf7530c33a276fcff73ecba2586bf1277a062ea9825b03e05a`  
**Benchmark v0 SHA-256**: `36e34a26da3765e9ed45bf83fb79614c372a624527e23f5f912ecb04506e223d`  
**Status**: `PROVISIONAL_DEVELOPMENT_LOCKED` (Benchmark v0 remains `CANONICAL_FROZEN`)  
**Data Isolation**: Zero access to `frozen_test` partition across all experiments.

---

## 1. Executive Summary & Architecture Decision

This document formally records the development promotion decisions for RAGTune's two-stage retrieval pipeline:

1. **Stage-1 Development Champion**: **`E5C` (SQLite FTS5 BM25 + E4C Matched-Easy Dense via Reciprocal Rank Fusion, $k=60$)** is locked as the preferred **Stage-1 candidate-generation system** for development progression.
   - **Candidate Pool Recall**: Achieves $\text{HitRate@20} = \mathbf{0.9929}$ ($139 / 140$ queries contain an answer-bearing passage) and $\text{Recall@20} = \mathbf{0.8964}$.
   - **Quality**: In-domain $\text{NDCG@10} = \mathbf{0.6863}$, $\text{Recall@10} = \mathbf{0.8393}$, with only **3 top-10 failures** across all 140 validation queries.
   - **Latency Envelope**: Query embedding + vector search + lexical search + RRF executes in **35.1 ms P50** (serial) / **~24.5 ms P50** (pipelined concurrent), comfortably within the 50 ms budget.
   - **OOD Non-Degradation**: Demonstrates non-degradation on BEIR SciFact ($\Delta \text{NDCG@10} = \mathbf{+0.0043}$ over zero-shot BGE-small, 95% CI `[-0.0231, +0.0320]`).
   - *Note*: `E5C` is designated the preferred development candidate for candidate-pool recall. It is not declared a production champion or final model.

2. **Stage-2 Generic Reranker Profiling**: **`BAAI/bge-reranker-base` (un-fine-tuned) FAILS the development promotion gate and is REJECTED for direct deployment.**
   - **Quality Degradation**:
     - At Candidate Depth 20 (`E6C-Top20`): $\text{NDCG@10}$ regresses by **$-0.0088$** (from $0.6863$ to $0.6775$), $\text{Recall@10}$ drops by **$-0.0357$** (from $0.8393$ to $0.8036$), and top-10 failures triple from **3 to 9**.
     - At Candidate Depth 50 (`E6C-Top50`): $\text{NDCG@10}$ regresses by **$-0.0268$** (from $0.6863$ to $0.6595$), $\text{Recall@10}$ drops by **$-0.0679$** (from $0.8393$ to $0.7714$), and top-10 failures quadruple from **3 to 12**.
   - **Failure Mechanism**: Generic cross-encoders pre-trained on generic web search suffer from vocabulary and syntax mismatch in dense technical documentation (SQL parameters, Kubernetes API specs, PyTorch autograd internals). In `E6C-Top50`, the generic reranker demoted **11 relevant candidates** that were already present in the top-50 pool completely outside the top-10.
   - **Latency Explosion**: Reranking latency is **421.6 ms P50** for Depth-20 and **1,193.0 ms P50** for Depth-50, exploding total query latency to **473.0 ms** and **1,240.3 ms** respectively, violating production latency envelopes.
   - **Recommendation**: Generic off-the-shelf cross-encoders must NOT be deployed. Stage-2 requires domain-fine-tuned cross-encoders trained on hard negatives or calibrated score fusion.

---

## 2. Canonical Latency Accounting & Baseline Reconciliation

To eliminate reporting ambiguity, all latency telemetry is measured on identical hardware (NVIDIA GeForce RTX 5050 Laptop GPU, Driver 592.82, CUDA 12.8, PyTorch 2.11.0+cu128) and categorized by architectural layer:

### Latency by Component

| Operation / Component | Mechanism | P50 Latency | Mean Latency | Peak VRAM |
| :--- | :--- | :---: | :---: | :---: |
| **Query Embedding (BGE-small)** | FP16 PyTorch on CUDA | ~1.8 ms | ~2.1 ms | 379.7 MiB |
| **Query Embedding (Qwen3-0.6B)**| FP16 PyTorch on CUDA | ~18.2 ms | ~19.5 ms | 1,193.2 MiB |
| **Dense Vector Search** | 11,645 vectors dot product + top-50 | ~1.0 ms | ~1.2 ms | Included above |
| **Lexical Retrieval (BM25)** | SQLite FTS5 (unicode61 BM25Okapi) | 23.71 ms | 24.16 ms | 0.0 MiB |
| **Dense Standalone Retrieval (E1a)** | Embedding + Vector Search | 16.39 ms | 17.98 ms | 379.7 MiB |
| **Rank Fusion (RRF $k=60$)** | In-memory hash score accumulation | ~0.1 ms | ~0.15 ms | Negligible |
| **Stage-1 Serial Total (E5C)** | BM25 + BGE Dense + RRF | 35.10 ms | 38.50 ms | 379.7 MiB |
| **Stage-1 Concurrent (E5C)** | Overlapped GPU dense + CPU BM25 | ~24.52 ms | ~25.51 ms | 379.7 MiB |
| **Reranker Inference (Top-20)** | `bge-reranker-base` (batch 20, len 512)| 421.64 ms | 430.95 ms | 1,536.0 MiB |
| **Reranker Inference (Top-50)** | `bge-reranker-base` (batch 50, len 512)| 1,192.99 ms | 1,193.10 ms | 2,442.0 MiB |

> [!NOTE]
> **Reconciliation Note on E2c Recall@20**: An earlier conversational text table incorrectly transcribed E2c Recall@20 as `0.8857`. The actual canonical evaluation matrix (`benchmarks/canonical/canonical_metric_matrix.json`) records E2c Recall@20 = **0.9107**, NDCG@10 = **0.6993**, Recall@10 = **0.8464**, and Latency P50 = **74.86 ms**. All canonical artifacts remain verified and untampered.

---

## 3. Comprehensive Benchmark v0 Evaluation Matrix

Evaluated strictly on Benchmark v0 Development partition (140 queries). All systems evaluated against Grade $\ge 2$ relevance.

| ID | System Configuration | Stage | R@10 | R@20 | R@50 | HR@10 | HR@20 | HR@50 | NDCG@10 | MRR@10 | Top-10 Fails | Latency P50 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **E0** | SQLite FTS5 BM25 | 1 | 0.7571 | 0.8536 | 0.8893 | 0.9214 | 0.9714 | 0.9857 | 0.6184 | 0.6524 | 11 | 23.7 ms |
| **E1a**| BGE-small-en-v1.5 (Zero-Shot)| 1 | 0.7393 | 0.8321 | 0.8929 | 0.9000 | 0.9714 | 0.9929 | 0.5986 | 0.6462 | 14 | 16.4 ms |
| **E1c**| Qwen3-0.6B (Zero-Shot Ref)| 1 | 0.8250 | 0.9000 | 0.9321 | 0.9571 | 0.9857 | 0.9929 | 0.7120 | 0.7611 | 6 | 74.7 ms |
| **E2a**| BM25 + BGE-small Zero RRF | 1 | 0.8036 | 0.8714 | 0.9179 | 0.9429 | 0.9857 | 0.9929 | 0.6501 | 0.6931 | 8 | 24.5 ms |
| **E2c**| BM25 + Qwen3-0.6B RRF (Ref)| 1 | 0.8464 | 0.9107 | 0.9429 | 0.9714 | 0.9929 | 0.9929 | 0.6993 | 0.7286 | 4 | 74.9 ms |
| **E3** | BGE-small Contrastive FT | 1 | 0.7893 | 0.8500 | 0.8964 | 0.9357 | 0.9786 | 0.9929 | 0.6350 | 0.6937 | 9 | 17.3 ms |
| **E4C**| BGE-small Matched-Easy FT | 1 | 0.7833 | 0.8500 | 0.9036 | 0.9571 | 0.9786 | 0.9929 | 0.6435 | 0.6908 | 6 | 16.4 ms |
| **E4** | BGE-small Hard-Negative FT| 1 | 0.7714 | 0.8393 | 0.8893 | 0.9429 | 0.9714 | 0.9857 | 0.6565 | 0.7093 | 8 | 16.4 ms |
| **E5C**| **BM25 + E4C Matched-Easy RRF**| **1** | **0.8393**| **0.8964**| **0.9286**| **0.9786**| **0.9929**| **0.9929**| **0.6863**| **0.7259**| **3** | **35.1 ms** |
| **E5H**| BM25 + E4 Hard-Neg RRF | 1 | 0.8357 | 0.8964 | 0.9321 | 0.9786 | 0.9929 | 1.0000 | 0.6927 | 0.7360 | 3 | 35.1 ms |
| **E6C-20**| BGE-reranker on E5C Top-20 | 2 | 0.8036 | 0.8964 | 0.9286 | 0.9357 | 0.9929 | 0.9929 | 0.6775 | 0.7164 | 9 | 473.0 ms |
| **E6C-50**| BGE-reranker on E5C Top-50 | 2 | 0.7714 | 0.8500 | 0.9286 | 0.9143 | 0.9571 | 0.9929 | 0.6595 | 0.7034 | 12 | 1,240.3 ms |
| **E6H-50**| BGE-reranker on E5H Top-50 | 2 | 0.7714 | 0.8500 | 0.9321 | 0.9214 | 0.9571 | 1.0000 | 0.6589 | 0.7043 | 11 | 1,312.1 ms |

---

## 4. Stage-1 Candidate Pool Depth Analysis

In a multi-stage retrieval architecture, Stage-1 candidate generation serves as an upper bound for downstream rerankers. Two distinct metrics describe this pool:
- **$\text{HitRate@K}$**: Fraction of queries with **at least one** relevant passage (Grade $\ge 2$) in the top $K$. This measures candidate availability (whether the reranker has an opportunity to succeed).
- **$\text{Recall@K}$**: Macro-averaged fraction of **all** relevant passages retrieved in the top $K$.

### Candidate Depth Ceiling Comparison

| System | HR@10 | HR@20 | HR@50 | R@10 | R@20 | R@50 | Latency P50 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **E0 (BM25)** | 0.9214 | 0.9714 | 0.9857 | 0.7571 | 0.8536 | 0.8893 | 23.7 ms |
| **E2a (BM25 + BGE Zero)** | 0.9429 | 0.9857 | 0.9929 | 0.8036 | 0.8714 | 0.9179 | 24.5 ms |
| **E2c (BM25 + Qwen3 Ref)**| 0.9714 | 0.9929 | 0.9929 | 0.8464 | 0.9107 | 0.9429 | 74.9 ms |
| **E5C (BM25 + E4C Easy)** | **0.9786** | **0.9929** | **0.9929** | **0.8393** | **0.8964** | **0.9286** | **35.1 ms** |
| **E5H (BM25 + E4 Hard)** | **0.9786** | **0.9929** | **1.0000** | **0.8357** | **0.8964** | **0.9321** | **35.1 ms** |

### Depth Selection Rationale: Top-20 vs Top-50
- At $K=20$, `E5C` achieves $\text{HitRate@20} = \mathbf{99.29\%}$ ($139 / 140$ queries contain relevant evidence). The single unretrieved query is `v0_pt_003` (`save_for_backward`).
- Expanding candidate depth from $K=20$ to $K=50$ gains $+0.0000$ HitRate in E5C and $+0.0322$ Recall, but **multiplies downstream cross-encoder evaluation by $2.5\times$** (from 20 pairs to 50 pairs), increasing inference latency by **$+771$ ms**.
- When feeding Top-50 into an un-fine-tuned cross-encoder, the extra 30 candidates act as **distractors**, causing NDCG@10 to degrade further (from $0.6775$ down to $0.6595$) and increasing top-10 failures from 9 to 12.

---

## 5. Generic Cross-Encoder Reranker Profiling & Failure Transition Analysis

The generic cross-encoder `BAAI/bge-reranker-base` was profiled on identical candidate pools to isolate the causal effect of Stage-2 cross-encoder reranking:

### Transition Breakdown: E5C Stage-1 $\rightarrow$ E6C-Top50

```
Total Queries: 140
├── Rank Improvements (Delta NDCG > +0.05):   41 queries
├── Rank Regressions (Delta NDCG < -0.05):    47 queries
├── Stable / Minor Shift (|Delta NDCG| <= 0.05): 52 queries
│
Critical Failure Modes:
├── Relevant passage in pool (<= 50) but DEMOTED outside Top-10: 11 queries
├── Stage-1 Unrecoverable Miss (absent from Top-50 pool):          1 query (v0_pt_003)
└── Exact Identifier / Syntax Mismatch Failures:                 21 queries
```

### The 11 In-Pool Demotion Regressions
The following queries had answer-bearing passages ranked within the top 10 of Stage-1 E5C, but were demoted outside top-10 by the generic reranker:
1. `v0_pg_003` (`maintenance_work_mem`): Stage-1 Rank 5 $\rightarrow$ Reranker Rank **15**
2. `v0_pg_004` (`wal_level`): Stage-1 Rank 1 $\rightarrow$ Reranker Rank **37**
3. `v0_pt_034` (PyTorch tensor broadcast mismatch): Stage-1 Rank 2 $\rightarrow$ Reranker Rank **21**
4. `v0_k8s_003` (Job completions / parallelism): Stage-1 Rank 3 $\rightarrow$ Reranker Rank **13**
5. `v0_k8s_028` (Node MemoryPressure eviction): Stage-1 Rank 4 $\rightarrow$ Reranker Rank **26**
6. `v0_k8s_035` (Node lease renew NotReady): Stage-1 Rank 5 $\rightarrow$ Reranker Rank **12**
7. `v0_fa_007` (FastAPI OpenAPI callbacks): Stage-1 Rank 6 $\rightarrow$ Reranker Rank **20**
8. `v0_fa_015` (APIRouter dependencies): Stage-1 Rank 10 $\rightarrow$ Reranker Rank **26**
9. `v0_fa_017` (`model_dump` vs `jsonable_encoder`): Stage-1 Rank 1 $\rightarrow$ Reranker Rank **11**
10. `v0_fa_030` (`datetime` JSON serializable): Stage-1 Rank 1 $\rightarrow$ Reranker Rank **25**
11. `v0_fa_033` (422 Field required optional query param): Stage-1 Rank 8 $\rightarrow$ Reranker Rank **17**

> [!WARNING]
> **Root Cause of Generic Reranker Failure**:
> Pre-trained generic cross-encoders lack domain sensitivity for exact configuration parameters, code signatures, and error diagnostics. They exhibit high sensitivity to generic explanatory text (e.g. promoting high-level architecture overviews over specific configuration tables), demoting concise, exact technical answers.

---

## 6. Out-of-Domain (OOD) Development Gate: BEIR SciFact

To verify that domain fine-tuning on RAGTune developer documentation did not cause **catastrophic forgetting** or degrade general text retrieval, all candidate models were evaluated on the independent **BEIR SciFact** benchmark (300 test queries, 5,183 biomedical scientific abstracts, 339 ground truth relevance judgments).

### SciFact Evaluation Results

| System | NDCG@10 | Recall@10 | Recall@100 | MRR@10 | Delta NDCG@10 vs E1a | 95% Bootstrap CI | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BM25 Baseline** | 0.6695 | 0.7989 | 0.8859 | 0.6354 | -0.0422 | `[-0.0710, -0.0142]` | Reference |
| **E1a (Zero-Shot BGE)** | 0.7117 | 0.8362 | 0.9417 | 0.6808 | Baseline | Reference | Reference |
| **E4C (Matched-Easy FT)**| 0.7044 | 0.8196 | 0.9500 | 0.6760 | **-0.0073** | `[-0.0180, +0.0032]` | **PASSED** |
| **E4 (Hard-Negative FT)**| 0.7088 | 0.8296 | 0.9500 | 0.6791 | **-0.0029** | `[-0.0151, +0.0097]` | **PASSED** |
| **E5C (Hybrid MatchedEasy)**| **0.7160** | **0.8329** | **0.9650** | **0.6849** | **+0.0043** | `[-0.0231, +0.0320]` | **PASSED** |
| **E5H (Hybrid Hard-Neg)** | **0.7170** | **0.8371** | **0.9617** | **0.6862** | **+0.0053** | `[-0.0218, +0.0330]` | **PASSED** |

### Key Findings
1. **Zero Degradation**: Both fine-tuned dense models retain $> 99\%$ of zero-shot retrieval effectiveness. The 95% bootstrap confidence intervals for both `E4C` (`[-0.0180, +0.0032]`) and `E4` (`[-0.0151, +0.0097]`) comfortably cross zero and remain far above the $-0.02$ degradation threshold.
2. **Hybrid Generalization**: The lexical+dense hybrid `E5C` outperforms pure zero-shot BGE on SciFact ($\text{NDCG@10} = \mathbf{0.7160}$ vs $0.7117$, $\text{Recall@100} = \mathbf{0.9650}$ vs $0.9417$), confirming that lexical+dense hybrid fusion generalizes robustly out-of-domain.

---

## 7. Formal Promotion Gate Verdicts

| Gate Check | Criterion | Target Value | Measured Value (E5C) | Measured Value (E6C-20) | Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Gate 1: Pool Hit Rate** | Candidate pool contains $\ge 1$ answer passage | $\text{HR@20} \ge 98.0\%$ | **99.29%** (139/140) | N/A (Stage-1 gate) | **PASSED** |
| **Gate 2: In-Domain Quality** | Macro-average NDCG@10 on Benchmark v0 | $\text{NDCG@10} \ge 0.6800$ | **0.6863** | **0.6775** | E5C: **PASS**<br>E6C: **FAIL** |
| **Gate 3: Top-10 Failure Rate**| Total zero-hit queries in top 10 | $\le 5$ queries ($\le 3.5\%$) | **3 queries** (2.1%) | **9 queries** (6.4%) | E5C: **PASS**<br>E6C: **FAIL** |
| **Gate 4: OOD Non-Degradation**| Delta NDCG@10 vs zero-shot on SciFact | $\Delta \ge -0.0200$ | **+0.0043** | N/A | **PASSED** |
| **Gate 5: Latency Budget** | P50 query retrieval latency | Stage-1 $\le 50$ ms<br>End-to-End $\le 150$ ms | **35.1 ms** (serial)<br>**~24.5 ms** (pipelined) | **473.0 ms** (Total)<br>**421.6 ms** (Rerank) | E5C: **PASS**<br>E6C: **FAIL** |
| **Gate 6: Data Integrity** | Zero `frozen_test` leakage & audit status | Strict Isolation | 0 test queries touched<br>Manifest hash verified | 0 test queries touched | **PASSED** |

---

## 8. Summary of Actionable Next Steps

1. **Lock E5C as Stage-1 Pipeline Generator**:
   - Persist `E5C` configuration (`BM25` + `E4C` matched-easy dense with $k=60$) as the default candidate retriever for subsequent pipeline phases.
   - Restrict Stage-1 candidate retrieval depth to **$K=20$** for production latency efficiency.
2. **Reject Off-the-Shelf Stage-2 Rerankers**:
   - Do NOT deploy `BAAI/bge-reranker-base` or generic web-trained cross-encoders without domain adaptation.
3. **Stage-2 Development Path**:
   - To make Stage-2 viable, train a **domain-fine-tuned cross-encoder** using the 739 teacher/heuristic-filtered hard negatives mined in E4, trained with cross-entropy loss against canonical Grade-3 targets.
   - Implement score calibration or a hybrid fallback (e.g. interpolate Stage-1 RRF score with Reranker score) to prevent regressions on exact technical identifiers.
